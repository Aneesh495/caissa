"""Actual native draw histories and rehashed standalone/full-entry controls."""

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

from tests.full_bundle import fixture, reference, seal
from tools.campaign_process import Campaign, StageFailure, atomic
from verification.draw_history import PROFILE_SHA256


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--engine", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    from tools.heuristic_study import avoid_decisive_matches

    avoid_decisive_matches()
    root, engine = Path.cwd(), args.engine.resolve()
    profile = root / "config/draw-history-v1.json"
    network = root / "results/precision-v4-2026-10-25/selected-v4.cai"
    owner = Campaign(
        args.output,
        {
            "purpose": "Frozen G03 real histories and semantic controls",
            "full_acceptance": False,
        },
        600,
    )
    output = args.output.resolve()
    producer = output / "producer"
    py = sys.executable
    controls = []
    try:
        owner.run(
            "observe",
            [
                py,
                "-m",
                "tools.draw_history",
                "--engine",
                str(engine),
                "--network",
                str(network),
                "--profile",
                str(profile),
                "--expected-profile-sha256",
                PROFILE_SHA256,
                "--output",
                str(producer),
            ],
            180,
        )

        def command(evidence, destination):
            argv = [py, "-m", "verification.draw_history"]
            for name, path in [
                ("observations", evidence / "observations.jsonl"),
                ("summary", evidence / "SUMMARY.json"),
                ("config", evidence / "CONFIG.json"),
                ("engine", engine),
                ("network", network),
                ("profile", profile),
                ("output", destination),
            ]:
                argv += ["--" + name, str(path)]
            for name, value in [
                ("engine", sha(engine)),
                ("network", sha(network)),
                ("profile", PROFILE_SHA256),
                ("observations", sha(evidence / "observations.jsonl")),
            ]:
                argv += ["--expected-" + name + "-sha256", value]
            return argv

        owner.run("independent", command(producer, output / "independent"), 240)
        positive = json.loads((output / "independent/DRAW_HISTORY.json").read_text())
        assert positive["full_gate"] and all(positive["equal_board_witnesses"].values())
        original = [
            json.loads(row)
            for row in (producer / "observations.jsonl").read_text().splitlines()
        ]

        def reject(case, argv, reason, maximum=30, exit_code=1):
            try:
                owner.run(case, argv, maximum)
            except StageFailure as error:
                observed = json.loads((output / (case + ".log")).read_text())
                assert error.record["exit"] == exit_code and reason in observed.get(
                    "reason", ""
                ), (case, error.record, observed)
                controls.append(
                    {
                        "case": case,
                        "actual_exit": error.record["exit"],
                        "reason": observed["reason"],
                    }
                )
            else:
                raise AssertionError("draw verifier accepted " + case)

        for case in [
            "claim",
            "automatic",
            "null",
            "claim-moves",
            "bool-count",
            "history-key",
            "index",
            "missing-history",
            "false-count",
        ]:
            evidence = output / ("mutant-" + case)
            shutil.copytree(producer, evidence)
            rows = json.loads(json.dumps(original))
            if case == "claim":
                row = next(row for row in rows if row["rules"]["threefold_claim"])
                row["rules"]["threefold_claim"] = False
            elif case == "automatic":
                row = next(
                    row for row in rows if row["rules"]["terminal"] == "fivefold"
                )
                row["rules"]["terminal"] = "ongoing"
            elif case == "null":
                row = next(row for row in rows if row["rules"]["synthetic_depth"])
                row["rules"]["fifty_move_claim"] = True
            elif case == "claim-moves":
                row = next(row for row in rows if row["rules"]["claim_moves"])
                row["rules"]["claim_moves"] = []
            elif case == "bool-count":
                rows[0]["rules"]["repetitions"] = True
            elif case == "history-key":
                rows[0]["rules"]["search_key"] = "0" * 16
            elif case == "index":
                rows[0]["index"] = True
            elif case == "missing-history":
                del rows[1]
            elif case == "false-count":
                summary = json.loads((evidence / "SUMMARY.json").read_text())
                summary["observations"] += 1
                atomic(evidence / "SUMMARY.json", summary)
            (evidence / "observations.jsonl").write_text(
                "".join(json.dumps(row, separators=(",", ":")) + "\n" for row in rows)
            )
            summary = json.loads((evidence / "SUMMARY.json").read_text())
            summary["observations_sha256"] = sha(evidence / "observations.jsonl")
            atomic(evidence / "SUMMARY.json", summary)
            atomic(
                evidence / "REHASHED.json",
                {p.name: sha(p) for p in evidence.iterdir() if p.is_file()},
            )
            reason = (
                "schedule differs"
                if case in {"index", "missing-history"}
                else (
                    "completed counts differ"
                    if case == "false-count"
                    else "independent draw decision or wire type differs"
                )
            )
            reject(
                case,
                command(evidence, output / ("replay-" + case)),
                reason,
                90 if case == "false-count" else 30,
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
        (bundle / "draw").mkdir()
        for source, name in [
            (producer / "CONFIG.json", "CONFIG.json"),
            (producer / "SUMMARY.json", "SUMMARY.json"),
            (producer / "observations.jsonl", "observations.jsonl"),
            (profile, "profile.json"),
        ]:
            shutil.copy2(source, bundle / "draw" / name)
        arguments = {
            key: reference(bundle, "draw/" + name)
            for key, name in [
                ("config", "CONFIG.json"),
                ("summary", "SUMMARY.json"),
                ("observations", "observations.jsonl"),
                ("profile", "profile.json"),
            ]
        }
        domain = inputs["domains"]["G03"]
        domain.update(
            {
                "driver": "draw-history-v1",
                "draw_history": arguments,
                "artifacts": list(arguments.values()),
            }
        )

        def full(case, destination):
            pin = seal(bundle, inputs)
            return [
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
            owner.run("full-positive", full("positive", output / "full-replay"), 240)
        except StageFailure as error:
            result = json.loads((output / "full-positive.log").read_text())
            assert (
                error.record["exit"] == 2
                and result["status"] == "incomplete"
                and result["verified_semantic_gates"]["G03"]["full_gate"]
                and len(result["pending_semantic_gates"]) == 15
            ), result
        else:
            raise AssertionError("G03 alone manufactured full acceptance")
        reject(
            "full-inside",
            full("inside", bundle / "invalid-replay"),
            "preserve the original evidence",
        )
        domain["artifacts"] = list(arguments.values())[:-1]
        reject(
            "full-unlisted",
            full("unlisted", output / "unlisted"),
            "distinct declared raw artifacts",
        )
        domain["artifacts"] = list(arguments.values())
        arguments["summary"] = arguments["config"]
        reject(
            "full-alias",
            full("alias", output / "alias"),
            "distinct declared raw artifacts",
        )
        report = {
            "status": "passed",
            "positive": positive,
            "controls": controls,
            "full_acceptance": False,
        }
        atomic(output / "CONTROLS.json", report)
        owner.close("passed", report)
    except BaseException as error:
        owner.close("failed", {"error": repr(error)})
        raise


if __name__ == "__main__":
    main()
