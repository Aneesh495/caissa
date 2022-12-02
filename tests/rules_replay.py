"""Real native G01 prefix replay and rehashed semantic negative controls.

The prefix cannot pass the100000-position full gate. No engine is mocked.
"""

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

import chess

from tools.campaign_process import Campaign, StageFailure
from tests.full_bundle import fixture, reference, seal


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write(path, value):
    path.write_text(json.dumps(value, indent=2) + "\n")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--engine", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    from tools.heuristic_study import avoid_decisive_matches

    avoid_decisive_matches()
    root, engine = Path.cwd(), args.engine.resolve()
    c = Campaign(
        args.output,
        {
            "purpose": "Real saved-engine rules prefix and semantic mutation controls",
            "positions": 512,
            "perft_positions": 20,
            "full_acceptance": False,
        },
        240,
    )
    output = args.output.resolve()
    raw = output / "producer"
    protocol, fixtures = (
        root / "config/rules-replay-v1.json",
        root / "config/perft.json",
    )
    py = sys.executable
    results = []
    try:
        c.run(
            "producer",
            [
                py,
                "-m",
                "tools.differential",
                "--engine",
                str(engine),
                "--positions",
                "512",
                "--seed",
                "1729",
                "--output",
                str(raw),
            ],
            40,
        )

        def command(
            evidence,
            destination,
            rule=protocol,
            fixture=fixtures,
            mode="diagnostic",
            identity=None,
        ):
            return [
                py,
                "-m",
                "verification.rules",
                "--observations",
                str(evidence / "observations.jsonl"),
                "--summary",
                str(evidence / "summary.json"),
                "--engine",
                str(engine),
                "--expected-engine-sha256",
                identity or sha(engine),
                "--protocol",
                str(rule),
                "--expected-protocol-sha256",
                sha(rule),
                "--fixtures",
                str(fixture),
                "--expected-observations-sha256",
                sha(evidence / "observations.jsonl"),
                "--profile",
                mode,
                "--maximum-seconds",
                "60",
                "--output",
                str(destination),
            ]

        c.run("independent-prefix", command(raw, output / "independent"), 65)
        positive = json.loads((output / "independent/RULES.json").read_text())
        assert positive["positions"] == 512 and len(positive["perft"]) == 20
        assert positive["full_gate"] is False and positive["full_acceptance"] is False
        for case, reason in [
            ("move-sets", "independent oracle"),
            ("unreachable-walk", "frozen reachable walk"),
            ("duplicate-index", "frozen reachable walk"),
            ("false-perft", "perft total"),
            ("false-full-work", "useful-work"),
            ("engine-identity", "saved-engine identity"),
        ]:
            evidence = output / ("mutant-" + case)
            shutil.copytree(raw, evidence)
            rows = [
                json.loads(line)
                for line in (evidence / "observations.jsonl").read_text().splitlines()
            ]
            selected_rule, selected_fixtures = protocol, fixtures
            mode, identity = "diagnostic", None
            if case == "move-sets":
                rows[0]["actual"] = rows[0]["expected"] = rows[0]["expected"][1:]
            elif case == "unreachable-walk":
                board = chess.Board()
                board.push_uci("e2e4")
                rows[0]["fen"] = board.fen(en_passant="fen")
            elif case == "duplicate-index":
                rows[1]["i"] = 0
            elif case == "false-perft":
                selected_fixtures = evidence / "perft.json"
                value = json.loads(fixtures.read_text())
                value["positions"][0]["nodes"] += 1
                write(selected_fixtures, value)
                selected_rule = evidence / "rules.json"
                value = json.loads(protocol.read_text())
                value["perft_sha256"] = sha(selected_fixtures)
                write(selected_rule, value)
            elif case == "false-full-work":
                mode = "full"
            elif case == "engine-identity":
                identity = "0" * 64
            (evidence / "observations.jsonl").write_text(
                "".join(json.dumps(row, separators=(",", ":")) + "\n" for row in rows)
            )
            summary = json.loads((evidence / "summary.json").read_text())
            summary["observations_sha256"] = sha(evidence / "observations.jsonl")
            if case == "false-full-work":
                summary["requested"] = summary["completed"] = 100000
            write(evidence / "summary.json", summary)
            argv = command(
                evidence,
                output / ("replay-" + case),
                selected_rule,
                selected_fixtures,
                mode,
                identity,
            )
            try:
                c.run("control-" + case, argv, 65)
            except StageFailure as error:
                assert (
                    error.record["exit"] == 1
                    and error.record["reason"] == "nonzero-exit"
                ), error.record
                result = json.loads((output / ("control-" + case + ".log")).read_text())
                assert (
                    result["status"] == "rejected" and reason in result["reason"]
                ), result
                results.append(
                    {
                        "case": case,
                        "command": argv,
                        "exit": error.record["exit"],
                        "reason": result["reason"],
                        "raw_summary_profile_pins_rehashed": True,
                    }
                )
            else:
                raise AssertionError(
                    "rules verifier accepted semantic mutation " + case
                )
        # A real-source full bundle must reject a diagnostic prefix before
        # launching full native replay, and cannot write into its own evidence.
        commit = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], text=True, timeout=5
        ).strip()
        bundle = output / "full-bundle-prefix"
        inputs = fixture(bundle, root, root, commit)
        shutil.copy2(engine, bundle / "bin/caissa")
        inputs["engine"] = reference(bundle, "bin/caissa")
        for domain in inputs["domains"].values():
            domain["engine_sha256"] = inputs["engine"]["sha256"]
        (bundle / "rules").mkdir()
        for source, name in [
            (raw / "summary.json", "summary.json"),
            (raw / "observations.jsonl", "observations.jsonl"),
            (protocol, "profile.json"),
            (fixtures, "perft.json"),
        ]:
            shutil.copy2(source, bundle / "rules" / name)
        arguments = {
            name: reference(bundle, "rules/" + filename)
            for name, filename in [
                ("summary", "summary.json"),
                ("observations", "observations.jsonl"),
                ("profile", "profile.json"),
                ("fixtures", "perft.json"),
            ]
        }
        inputs["domains"]["G01"].update(
            {
                "driver": "rules-v1",
                "rules": arguments,
                "artifacts": list(arguments.values()),
            }
        )
        pin = seal(bundle, inputs)
        for case, destination, reason in [
            ("full-adapter-prefix", output / "full-replay", "all100000"),
            (
                "full-adapter-output",
                bundle / "invalid-replay",
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
                c.run(case, argv, 30)
            except StageFailure as error:
                result = json.loads((output / (case + ".log")).read_text())
                assert error.record["exit"] == 1 and reason in result["reason"], (
                    error.record,
                    result,
                )
                assert not destination.exists()
                results.append(
                    {
                        "case": case,
                        "command": argv,
                        "exit": 1,
                        "reason": result["reason"],
                        "raw_summary_profile_pins_rehashed": True,
                    }
                )
            else:
                raise AssertionError(
                    "full adapter accepted a prefix or evidence mutation"
                )
        result = {
            "status": "passed",
            "native_prefix_positions": 512,
            "independent_perft_positions": 20,
            "positive_full_gate": False,
            "controls": results,
            "engine_sha256": sha(engine),
            "scope": "Real original-core diagnostic replay; full100000-position final-source gate remains unexecuted",
            "full_acceptance": False,
        }
        write(output / "CONTROLS.json", result)
        c.close("passed diagnostic rules controls", result)
        print(json.dumps(result))
    except BaseException as error:
        c.close("failed", {"error": repr(error), "full_acceptance": False})
        raise


if __name__ == "__main__":
    main()
