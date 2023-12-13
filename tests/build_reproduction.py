"""Actual fresh builds, independent dependency replay and rehashed semantic controls."""

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from verification.build_reproduction import verify


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n")


def seal(root):
    write(
        root / "MANIFEST.json",
        {
            "files": {
                str(p.relative_to(root)): sha(p)
                for p in sorted(root.rglob("*"))
                if p.is_file()
                and p.name != "MANIFEST.json"
                and not any(
                    part in {"checkout", "work"} for part in p.relative_to(root).parts
                )
            }
        },
    )


def compact_copy(source, target):
    shutil.copytree(
        source,
        target,
        ignore=lambda _path, names: [
            name for name in names if name in {"checkout", "work"}
        ],
    )


def public_copy(source, target):
    """Keep project/build payloads and explicit platform dependency identities."""
    compact_copy(source, target)
    omitted = []
    for label in ["build-1", "build-2"]:
        trace = target / label / "trace"
        if not trace.exists():
            continue
        retain = set()
        for path in trace.glob("*.json"):
            value = json.loads(path.read_text())
            if value["output"]:
                retain.add(value["output"]["sha256"])
            for row in value["inputs_before"]:
                if value["mode"] == "link" or Path(row["path"]).is_relative_to(
                    value["checkout"]
                ):
                    retain.add(row["sha256"])
        for path in (trace / "blobs").glob("*"):
            if path.name not in retain:
                omitted.append(
                    {
                        "path": str(path.relative_to(target)),
                        "sha256": sha(path),
                        "bytes": path.stat().st_size,
                    }
                )
                path.unlink()
    for path in (target / "toolchain/blobs").glob("*"):
        omitted.append(
            {
                "path": str(path.relative_to(target)),
                "sha256": sha(path),
                "bytes": path.stat().st_size,
            }
        )
        path.unlink()
    write(
        target / "PUBLIC_TRANSPORT.json",
        {
            "schema": "caissa-build-public-subset-v1",
            "complete_platform_input_transport": False,
            "omitted_platform_bodies": omitted,
            "project_and_object_payloads_preserved": True,
            "reason": "Installed compiler and system SDK bodies remain platform inputs; the public subset carries their exact identities. Full portable reproduction remains pending.",
        },
    )
    seal(target)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output = args.output.resolve()
    args.output.mkdir(parents=True, exist_ok=False)
    project = Path(__file__).resolve().parents[1]
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    profile_sha = sha(project / "config/build-attribution-v1.json")
    limits = json.loads(
        (project / "config/build-attribution-amendment-v1.json").read_text()
    )
    root = args.output / "positive"
    started = time.monotonic()
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "tools.build_reproduction",
            "--checkout",
            str(project),
            "--expected-commit",
            head,
            "--profile-sha256",
            profile_sha,
            "--output",
            str(root),
        ],
        capture_output=True,
        text=True,
        timeout=min(950, limits["deadline_unix"] - time.time()),
    )
    (args.output / "producer.log").write_text(result.stdout + result.stderr)
    print(result.stdout + result.stderr, flush=True)
    if result.returncode:
        if root.exists():
            try:
                public_copy(root, args.output / "public")
            except Exception as error:
                write(
                    args.output / "PUBLIC_SUBSET_FAILURE.json",
                    {"reason": str(error), "producer_failure_preserved": True},
                )
        raise ValueError("actual compiler attribution producer failed")
    seal(root)
    public_copy(root, args.output / "public")
    positive = verify(
        root,
        project,
        head,
        profile_sha,
        replay_dependencies=True,
        deadline=limits["deadline_unix"],
        replay_output=args.output / "independent",
    )
    write(args.output / "INDEPENDENT.json", positive)
    print("INDEPENDENT", json.dumps(positive), flush=True)
    results = [
        {
            "case": "real-independent-compiler-input-and-archive-replay",
            "observed": positive,
        }
    ]
    cases = [
        "missing-unit",
        "wrong-source-blob",
        "changed-compiler",
        "input-mutated-after-compile",
        "dependency-omitted",
        "compile-graph-disagrees",
        "failed-compile-promoted",
        "linked-main-replaced",
        "core-object-omitted",
        "linked-output-replaced",
        "different-second-image",
        "wrong-source-commit",
        "promoted-full-gate",
    ]
    for case in cases:
        if time.time() >= limits["deadline_unix"] or time.monotonic() - started >= 1100:
            raise TimeoutError("build attribution control deadline exhausted")
        with tempfile.TemporaryDirectory(prefix="caissa-build-forgery-") as temporary:
            folder = Path(temporary) / "raw"
            compact_copy(root, folder)
            path = folder / "build-1/trace/apps_main.cpp.json"
            record = json.loads(path.read_text())
            if case == "missing-unit":
                path.unlink()
            elif case == "wrong-source-blob":
                source = next(
                    row
                    for row in record["inputs_before"]
                    if row["path"].endswith("/apps/main.cpp")
                )
                source["sha256"] = record["output"]["sha256"]
                source["bytes"] = record["output"]["bytes"]
                record["inputs_after"] = json.loads(json.dumps(record["inputs_before"]))
                write(path, record)
            elif case == "changed-compiler":
                record["compiler"]["sha256"] = "0" * 64
                write(path, record)
            elif case == "input-mutated-after-compile":
                record["inputs_after"][0]["sha256"] = "0" * 64
                write(path, record)
            elif case == "dependency-omitted":
                record["inputs_before"].pop()
                record["inputs_after"] = json.loads(json.dumps(record["inputs_before"]))
                write(path, record)
            elif case == "compile-graph-disagrees":
                record["argv"].append("-DUNOBSERVED=1")
                write(path, record)
            elif case == "failed-compile-promoted":
                record["exit"] = 1
                write(path, record)
            elif case in {
                "linked-main-replaced",
                "core-object-omitted",
                "linked-output-replaced",
            }:
                path = folder / "build-1/trace/link.json"
                record = json.loads(path.read_text())
                if case == "linked-main-replaced":
                    row = next(
                        r for r in record["inputs_before"] if r["path"].endswith(".o")
                    )
                    row["sha256"] = record["output"]["sha256"]
                    row["bytes"] = record["output"]["bytes"]
                    record["inputs_after"] = json.loads(
                        json.dumps(record["inputs_before"])
                    )
                elif case == "core-object-omitted":
                    record["inputs_before"] = record["inputs_before"][:1]
                    record["inputs_after"] = record["inputs_before"]
                else:
                    record["output"] = record["inputs_before"][0]
                write(path, record)
            elif case == "different-second-image":
                path = folder / "build-2/caissa"
                path.write_bytes(path.read_bytes() + b"changed")
            elif case == "wrong-source-commit":
                path = folder / "SOURCE_INPUTS.json"
                record = json.loads(path.read_text())
                record["commit"] = "0" * 40
                write(path, record)
            else:
                path = folder / "PROFILE.json"
                record = json.loads(path.read_text())
                record["full_G15_certified"] = True
                write(path, record)
            seal(folder)
            try:
                verify(
                    folder, project, head, profile_sha, deadline=limits["deadline_unix"]
                )
            except (ValueError, FileNotFoundError, KeyError, StopIteration) as error:
                results.append({"case": case, "rejected": True, "reason": str(error)})
            else:
                raise AssertionError("semantic build forgery accepted: " + case)
    try:
        verify(args.output / "public", project, head, profile_sha)
    except FileNotFoundError:
        results.append(
            {
                "case": "public-metadata-is-not-full-platform-reproduction",
                "rejected": True,
            }
        )
    else:
        raise AssertionError("incomplete public platform payload accepted")
    write(
        args.output / "CONTROLS.json",
        {"status": "passed", "cases": results, "full_G15_certified": False},
    )
    print(
        json.dumps(
            {
                "status": "passed",
                "cases": len(results),
                "seconds": time.monotonic() - started,
                "full_G15_certified": False,
                "full_acceptance": False,
            }
        )
    )


if __name__ == "__main__":
    main()
