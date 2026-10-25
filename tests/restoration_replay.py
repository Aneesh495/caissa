"""Real native restoration prefix, rehashed mutations and full-entry controls."""

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

from tests.full_bundle import fixture, reference, seal
from tools.campaign_process import Campaign, StageFailure

PROFILE_SHA256 = "6cde330d87e49084135760cb737f3c2756a594a69b4ed709e21b98df5f9e584c"


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write(path, value):
    path.write_text(json.dumps(value, separators=(",", ":"), allow_nan=False) + "\n")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--engine", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    from tools.heuristic_study import avoid_decisive_matches

    avoid_decisive_matches()
    root, engine, py = Path.cwd(), args.engine.resolve(), sys.executable
    network, profile = (
        root / "results/precision-v4-2026-10-25/selected-v4.cai",
        root / "config/restoration-v1.json",
    )
    owner = Campaign(
        args.output,
        {
            "pairs": 1280,
            "purpose": "Real saved-native restoration controls",
            "full_acceptance": False,
        },
        300,
    )
    output = args.output.resolve()
    producer = output / "producer"
    controls = []
    try:
        owner.run(
            "producer",
            [
                py,
                "-m",
                "tools.restoration",
                "--engine",
                str(engine),
                "--network",
                str(network),
                "--pairs",
                "1280",
                "--maximum-seconds",
                "60",
                "--expected-profile-sha256",
                PROFILE_SHA256,
                "--output",
                str(producer),
            ],
            65,
        )

        def command(evidence, destination, mode="diagnostic"):
            return [
                py,
                "-m",
                "verification.restoration",
                "--observations",
                str(evidence / "observations.jsonl"),
                "--config",
                str(evidence / "CONFIG.json"),
                "--summary",
                str(evidence / "SUMMARY.json"),
                "--engine",
                str(engine),
                "--network",
                str(network),
                "--profile",
                str(profile),
                "--expected-engine-sha256",
                sha(engine),
                "--expected-network-sha256",
                sha(network),
                "--expected-profile-sha256",
                PROFILE_SHA256,
                "--expected-observations-sha256",
                sha(evidence / "observations.jsonl"),
                "--output",
                str(destination),
                "--mode",
                mode,
                "--maximum-seconds",
                "60",
            ]

        owner.run("independent-prefix", command(producer, output / "independent"), 65)
        positive = json.loads((output / "independent-prefix.log").read_text())
        assert (
            positive["pairs"] == 1280
            and positive["full_gate"] is False
            and positive["native_exit"] == 0
        )
        originals = [
            json.loads(line)
            for line in (producer / "observations.jsonl").read_text().splitlines()
        ]
        first = next(i for i, row in enumerate(originals) if row["kind"] == "trial")
        cases = [
            ("clock", "fresh native restoration response differs"),
            ("rights", "fresh native restoration response differs"),
            ("history", "fresh native restoration response differs"),
            ("accumulator", "fresh native restoration response differs"),
            ("boolean-piece", "wire type differs: board"),
            ("score", "fresh native restoration response differs"),
            ("index", "reachable sequence index differs"),
            ("false-full", "missing or excessive restoration observation"),
            ("prefix-full", "all1000000 make/unmake pairs"),
        ]
        for case, reason in cases:
            evidence = output / ("mutant-" + case)
            shutil.copytree(producer, evidence)
            rows = json.loads(json.dumps(originals))
            row = rows[first]
            if case == "clock":
                row["after"]["halfmove"] += 1
            elif case == "rights":
                row["after"]["rights"][0][0] = 64
            elif case == "history":
                row["after"]["history"][-1] = "f" * 16
            elif case == "accumulator":
                row["after"]["accumulator"][0][0] += 1
            elif case == "boolean-piece":
                row["after"]["board"][row["after"]["board"].index(1)] = True
            elif case == "score":
                row["after"]["native"] += 1
            elif case == "index":
                row["index"] += 1
            elif case == "false-full":
                config, summary = json.loads(
                    (evidence / "CONFIG.json").read_text()
                ), json.loads((evidence / "SUMMARY.json").read_text())
                config["pairs"] = summary["pairs"] = 1000000
                write(evidence / "CONFIG.json", config)
                write(evidence / "SUMMARY.json", summary)
            (evidence / "observations.jsonl").write_text(
                "".join(
                    json.dumps(value, separators=(",", ":")) + "\n" for value in rows
                )
            )
            summary = json.loads((evidence / "SUMMARY.json").read_text())
            summary["observations_sha256"] = sha(evidence / "observations.jsonl")
            write(evidence / "SUMMARY.json", summary)
            write(
                evidence / "REHASHED.json",
                {p.name: sha(p) for p in evidence.iterdir() if p.is_file()},
            )
            try:
                owner.run(
                    case,
                    command(
                        evidence,
                        output / ("replay-" + case),
                        "full" if case.endswith("full") else "diagnostic",
                    ),
                    65,
                )
            except StageFailure as error:
                result = json.loads((output / (case + ".log")).read_text())
                assert error.record["exit"] == 1 and reason in result["reason"], (
                    case,
                    result,
                )
                controls.append(
                    {
                        "case": case,
                        "actual_exit": error.record["exit"],
                        "reason": result["reason"],
                    }
                )
            else:
                raise AssertionError("restoration verifier accepted " + case)
        commit = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], text=True, timeout=5
        ).strip()
        bundle = output / "full-bundle"
        inputs = fixture(bundle, root, root, commit)
        shutil.copy2(engine, bundle / "bin/caissa")
        inputs["engine"] = reference(bundle, "bin/caissa")
        for domain in inputs["domains"].values():
            domain["engine_sha256"] = inputs["engine"]["sha256"]
        (bundle / "restoration").mkdir()
        for source, name in [
            (producer / "CONFIG.json", "CONFIG.json"),
            (producer / "SUMMARY.json", "SUMMARY.json"),
            (producer / "observations.jsonl", "observations.jsonl"),
            (profile, "profile.json"),
        ]:
            shutil.copy2(source, bundle / "restoration" / name)
        arguments = {
            key: reference(bundle, "restoration/" + name)
            for key, name in [
                ("config", "CONFIG.json"),
                ("summary", "SUMMARY.json"),
                ("observations", "observations.jsonl"),
                ("profile", "profile.json"),
            ]
        }
        inputs["domains"]["G02"].update(
            {
                "driver": "restoration-v1",
                "restoration": arguments,
                "artifacts": list(arguments.values()),
            }
        )
        pin = seal(bundle, inputs)
        for case, destination, reason in [
            (
                "full-entry-prefix",
                output / "full-replay",
                "all1000000 make/unmake pairs",
            ),
            (
                "full-entry-output",
                bundle / "invalid-output",
                "preserve the original evidence",
            ),
        ]:
            argv = [
                py,
                "-m",
                "verification.verify",
                str(bundle),
                "--checkout",
                str(root),
                "--expected-commit",
                commit,
                "--profile",
                "full",
                "--expected-inputs-sha256",
                pin,
                "--replay-output",
                str(destination),
            ]
            try:
                owner.run(case, argv, 30)
            except StageFailure as error:
                result = json.loads((output / (case + ".log")).read_text())
                assert error.record["exit"] == 1 and reason in result["reason"], (
                    case,
                    result,
                )
                assert not destination.exists()
                controls.append(
                    {
                        "case": case,
                        "actual_exit": error.record["exit"],
                        "reason": result["reason"],
                    }
                )
            else:
                raise AssertionError("full restoration adapter accepted " + case)
        report = {
            "status": "passed",
            "positive": positive,
            "controls": controls,
            "scope": "Real1280-pair restoration prefix; full million-pair final-source gate remains required",
            "full_acceptance": False,
        }
        write(output / "CONTROLS.json", report)
        owner.close("passed", report)
    except BaseException as error:
        owner.close("failed", {"error": repr(error)})
        raise


if __name__ == "__main__":
    main()
