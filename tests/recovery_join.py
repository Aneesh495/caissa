"""Join actual historical component archives without rerunning their producers."""

import argparse
import contextlib
import copy
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

from tests.full_bundle import fixture, reference, sha, write
from tools.host_lease import ENVIRONMENT, HostLease
from tools.recovery_join_inputs import prepare
from verification.recovery_join import source_boundaries


def seal(root, inputs=None):
    if inputs is not None:
        write(root / "FULL_INPUTS.json", inputs)
    write(
        root / "MANIFEST.json",
        {
            "files": {
                str(p.relative_to(root)): sha(p)
                for p in sorted(root.rglob("*"))
                if p.is_file() and p != root / "MANIFEST.json"
            }
        },
    )
    return sha(root / "MANIFEST.json" if inputs is None else root / "FULL_INPUTS.json")


def copy_input(origin, target):
    if Path(origin).suffix == ".zip":
        os.link(origin, target)
        return str(target)
    return shutil.copy2(origin, target)


def footprint_controls(project, source, rule, origins, output):
    results = []
    environment = {
        **os.environ,
        "GIT_INDEX_FILE": str(output / "FOOTPRINT_INDEX"),
        "GIT_AUTHOR_NAME": "fixture",
        "GIT_AUTHOR_EMAIL": "fixture@invalid",
        "GIT_COMMITTER_NAME": "fixture",
        "GIT_COMMITTER_EMAIL": "fixture@invalid",
    }

    def git(arguments, input_bytes=None):
        return (
            subprocess.run(
                ["git", *arguments],
                cwd=project,
                env=environment,
                input=input_bytes,
                capture_output=True,
                check=True,
                timeout=10,
            )
            .stdout.strip()
            .decode()
        )

    original = (project / "training/train.py").read_bytes()
    for case, mode, raw in [
        (
            "committed-producer-edit",
            "100644",
            original + b"\n# altered committed producer fixture\n",
        ),
        ("committed-producer-mode", "100755", original),
    ]:
        git(["read-tree", source])
        blob = git(["hash-object", "-w", "--stdin"], raw)
        git(["update-index", "--cacheinfo", mode, blob, "training/train.py"])
        tree = git(["write-tree"])
        candidate = git(
            ["commit-tree", tree, "-p", source], b"source-bound recovery join forgery\n"
        )
        try:
            source_boundaries(project, candidate, rule, origins)
        except ValueError as error:
            assert "producer footprint differs" in str(error), str(error)
            results.append(
                {
                    "case": case,
                    "actual_committed_source": candidate,
                    "rejection": str(error),
                }
            )
        else:
            raise AssertionError("G11 changed committed producer source admitted")
    assert (
        subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=project, text=True
        ).strip()
        == source
    )
    return results


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    project = Path(__file__).resolve().parents[1]
    scope = json.loads(
        (project / "config/recovery-join-development-v1.json").read_text()
    )
    assert time.time() < scope["deadline_unix"]
    with contextlib.closing(HostLease(project / "runs")) as lease:
        os.environ[ENVIRONMENT] = str(lease.stream.fileno())
        raw = output / "original-inputs"
        prepared = prepare(raw)
        os.environ.pop("GH_TOKEN", None)
        retained = output / "retained-archives"
        retained.mkdir()
        for archive in (raw / "archives").glob("*.zip"):
            os.link(archive, retained / archive.name)
        write(output / "PREPARED.json", prepared)
        source = prepared["source_commit"]
        rule = json.loads((raw / "PROFILE.json").read_text())
        origins = json.loads((raw / "ARTIFACTS.json").read_text())
        controls = footprint_controls(project, source, rule, origins, output)
        write(output / "SOURCE_CONTROLS.json", controls)
        original = output / "original-full"
        baseline = fixture(original, project, project, source)
        shutil.copy2(project / "config/protocol-v4.json", original / "protocol.json")
        shutil.copy2(raw / "engine", original / "bin/caissa")
        baseline["protocol"] = reference(original, "protocol.json")
        baseline["engine"] = reference(original, "bin/caissa")
        for domain in baseline["domains"].values():
            domain["engine_sha256"] = baseline["engine"]["sha256"]
        shutil.copytree(raw, original / "g11-join", copy_function=copy_input)
        domain = baseline["domains"]["G11"]
        domain.update(
            driver="forced-recovery-join-v1",
            recovery_join={"config": reference(original, "g11-join/CONFIG.json")},
            artifacts=[
                reference(original, str(p.relative_to(original)))
                for p in sorted((original / "g11-join").rglob("*"))
                if p.is_file()
            ],
        )
        seal(original, baseline)
        for case in [
            "positive-full-entry",
            "missing-replay-output",
            "missing-component",
            "swapped-original-zips",
            "changed-historical-source",
            "changed-final-actor",
            "undeclared-original-archive",
        ]:
            root = output / case
            shutil.copytree(original, root, copy_function=copy_input)
            inputs = copy.deepcopy(baseline)
            cfg_path = root / "g11-join/CONFIG.json"
            cfg = json.loads(cfg_path.read_text())
            if case == "missing-component":
                del cfg["archives"]["training"]
            elif case == "swapped-original-zips":
                cfg["archives"]["arena"], cfg["archives"]["training"] = (
                    cfg["archives"]["training"],
                    cfg["archives"]["arena"],
                )
            elif case == "changed-historical-source":
                value = json.loads((root / "g11-join/ARTIFACTS.json").read_text())
                value["arena"]["source_commit"] = "0" * 40
                write(root / "g11-join/ARTIFACTS.json", value)
            elif case == "changed-final-actor":
                cfg["engine_sha256"] = "0" * 64
            write(cfg_path, cfg)
            seal(root / "g11-join")
            domain = inputs["domains"]["G11"]
            domain["recovery_join"]["config"] = reference(root, "g11-join/CONFIG.json")
            domain["artifacts"] = [
                reference(root, str(p.relative_to(root)))
                for p in sorted((root / "g11-join").rglob("*"))
                if p.is_file()
                and not (
                    case == "undeclared-original-archive"
                    and str(p.relative_to(root)) == "g11-join/archives/training.zip"
                )
            ]
            pin = seal(root, inputs)
            command = [
                sys.executable,
                "-B",
                "-m",
                "verification.full_bundle",
                str(root),
                "--checkout",
                str(project),
                "--expected-commit",
                source,
                "--expected-inputs-sha256",
                pin,
                "--maximum-seconds",
                "600",
            ]
            if case != "missing-replay-output":
                command += ["--replay-output", str(output / (case + "-replay"))]
            run = subprocess.run(
                command,
                cwd=project,
                capture_output=True,
                text=True,
                timeout=620,
                pass_fds=(lease.stream.fileno(),),
            )
            result = json.loads(run.stdout)
            write(
                output / (case + "-RESULT.json"),
                {
                    "command": command,
                    "exit": run.returncode,
                    "observed": result,
                    "stderr": run.stderr,
                    "ordinary_manifest_and_external_inputs_pin_recomputed": True,
                },
            )
            assert result["full_acceptance"] is False
            if case == "positive-full-entry":
                assert run.returncode == 2, result
                saved = sys.platform == "darwin"
                section = (
                    "verified_semantic_gates"
                    if saved
                    else "verified_semantic_components"
                )
                joined = result[section]["G11"]
                assert joined["full_G11_saved_image_sample"] is saved
                assert len(result["pending_semantic_gates"]) == (15 if saved else 16)
                if saved:
                    assert joined["saved_native_resumption"]["new_games_executed"] == 3
            elif case == "missing-replay-output":
                assert (
                    run.returncode == 2 and len(result["pending_semantic_gates"]) == 16
                ), result
            else:
                assert run.returncode == 1 and result["status"] == "rejected", result
                reason = {
                    "missing-component": "required component inventory differs",
                    "swapped-original-zips": "ZIP identity or role differs",
                    "changed-historical-source": "artifact catalog differs",
                    "changed-final-actor": "saved final actor",
                    "undeclared-original-archive": "archive inventory",
                }[case]
                assert reason in result["reason"], result
            controls.append({"case": case, "actual_exit": run.returncode})
            write(output / "JOIN_CONTROLS.json", controls)
            assert (
                sum(p.stat().st_size for p in output.rglob("*") if p.is_file())
                <= scope["maximum_output_bytes_per_platform"]
            ), "G11 development retained output bound exhausted"
        write(
            output / "ARCHIVE_ALIASES.json",
            {
                "scope": "Duplicate unmodified ZIP copies are omitted from hosted upload; reconstruct each exact path from this pinned canonical archive.",
                "files": {
                    str(p.relative_to(output)): {
                        "canonical": "retained-archives/" + p.name,
                        "sha256": prepared["archives"][p.stem]["sha256"],
                    }
                    for p in output.rglob("*.zip")
                    if p.parent.name == "archives"
                },
            },
        )
        report = {
            "status": "passed",
            "source_commit": source,
            "full_G11_saved_image_sample": sys.platform == "darwin",
            "controls": len(controls),
            "historical_producers_rerun": False,
            "new_training": False,
            "new_acquisition": False,
            "new_strength_games": 0,
            "new_native_resumption_diagnostic_games": (
                3 if sys.platform == "darwin" else 0
            ),
            "full_acceptance": False,
        }
        write(output / "CONTROLS.json", report)
        print(json.dumps(report))
        del os.environ[ENVIRONMENT]


if __name__ == "__main__":
    main()
