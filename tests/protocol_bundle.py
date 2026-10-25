"""Real UCI prefix through full admission, retaining honest sample rejection."""

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

from tests.full_bundle import fixture, reference, seal
from tools.campaign_process import Campaign, StageFailure


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--engine", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    from tools.heuristic_study import avoid_decisive_matches

    avoid_decisive_matches()
    root, engine, py = Path.cwd(), args.engine.resolve(), sys.executable
    campaign = Campaign(
        args.output,
        {
            "sequences": 32,
            "ponder_sequences": 100,
            "purpose": "Real prefix/full-entry protocol controls",
            "full_acceptance": False,
        },
        180,
    )
    output, controls = args.output.resolve(), []
    raw = output / "producer"
    try:
        campaign.run(
            "producer",
            [
                py,
                "-m",
                "tools.protocol_campaign",
                "--engine",
                str(engine),
                "--sequences",
                "32",
                "--max-seconds",
                "60",
                "--output",
                str(raw),
            ],
            65,
        )
        campaign.run(
            "independent-prefix",
            [py, "-m", "verification.protocol", str(raw), "--engine", str(engine)],
            15,
        )
        prefix = json.loads((output / "independent-prefix.log").read_text())
        assert (
            prefix["completed"] == 32
            and prefix["ponder_completed"] == 100
            and prefix["full_acceptance"] is False
        )
        commit = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], text=True, timeout=5
        ).strip()
        bundle = output / "full-bundle"
        inputs = fixture(bundle, root, root, commit)
        shutil.copy2(engine, bundle / "bin/caissa")
        inputs["engine"] = reference(bundle, "bin/caissa")
        for domain in inputs["domains"].values():
            domain["engine_sha256"] = inputs["engine"]["sha256"]
        (bundle / "uci").mkdir()
        files = {
            "config": "CONFIG.json",
            "summary": "summary.json",
            "transcript": "transcript.jsonl",
            "stderr": "stderr.log",
        }
        for name in files.values():
            shutil.copy2(raw / name, bundle / "uci" / name)
        arguments = {
            key: reference(bundle, "uci/" + name) for key, name in files.items()
        }
        domain = inputs["domains"]["G04"]
        domain.update(
            {
                "driver": "protocol-v2",
                "uci_transcript": arguments,
                "artifacts": list(arguments.values()),
            }
        )
        original_config = json.loads((bundle / "uci/CONFIG.json").read_text())
        original_summary = json.loads((bundle / "uci/summary.json").read_text())
        cases = [
            ("prefix", "full protocol workload below 10000"),
            ("unlisted", "absent from its declared raw artifacts"),
            ("aliased", "requires distinct raw artifacts"),
            ("different-runtime", "transcript executable differs"),
            ("false-full-count", "missing protocol sequences"),
            ("inside-evidence", "preserve the original evidence"),
        ]
        for case, reason in cases:
            config, summary = dict(original_config), dict(original_summary)
            domain["uci_transcript"] = dict(arguments)
            domain["artifacts"] = list(arguments.values())
            destination = output / ("replay-" + case)
            if case == "unlisted":
                domain["artifacts"] = domain["artifacts"][:-1]
            elif case == "aliased":
                domain["uci_transcript"]["stderr"] = arguments["transcript"]
            elif case == "different-runtime":
                config.update(requested=10000, engine_sha256="f" * 64)
            elif case == "false-full-count":
                config["requested"] = summary["requested"] = summary["completed"] = (
                    10000
                )
            elif case == "inside-evidence":
                destination = bundle / "invalid-output"
            for name, value in [("CONFIG.json", config), ("summary.json", summary)]:
                (bundle / "uci" / name).write_text(json.dumps(value) + "\n")
            for key in ["config", "summary"]:
                fresh = reference(bundle, "uci/" + files[key])
                domain["uci_transcript"][key] = fresh
                domain["artifacts"] = [
                    fresh if ref["path"] == fresh["path"] else ref
                    for ref in domain["artifacts"]
                ]
            pin = seal(bundle, inputs)
            command = [
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
                campaign.run(case, command, 15)
            except StageFailure as error:
                result = json.loads((output / (case + ".log")).read_text())
                assert error.record["exit"] == 1 and reason in result["reason"], (
                    case,
                    result,
                )
                if case != "false-full-count":
                    assert not destination.exists()
                controls.append(
                    {
                        "case": case,
                        "actual_exit": error.record["exit"],
                        "reason": result["reason"],
                    }
                )
            else:
                raise AssertionError("full protocol adapter accepted " + case)
        report = {
            "status": "passed",
            "prefix": prefix,
            "controls": controls,
            "scope": "Real32-sequence prefix and100ponder cases; cannot satisfy full10000 gate",
            "full_acceptance": False,
        }
        (output / "CONTROLS.json").write_text(json.dumps(report, indent=2) + "\n")
        campaign.close("passed", report)
    except BaseException as error:
        campaign.close("failed", {"error": repr(error)})
        raise


if __name__ == "__main__":
    main()
