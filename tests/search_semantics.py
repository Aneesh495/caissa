"""Real exact search/table campaign with semantic and full-entry controls."""

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

from tests.full_bundle import fixture, reference, seal
from tools.campaign_process import Campaign, StageFailure, atomic
from verification.search_semantics import PROFILE_SHA256


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--engine", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    from tools.heuristic_study import avoid_decisive_matches

    avoid_decisive_matches()
    root, engine, py = Path.cwd(), args.engine.resolve(), sys.executable
    profile = root / "config/search-semantics-v1.json"
    output = args.output.resolve()
    producer = output / "producer"
    c = Campaign(
        output,
        {
            "purpose": "Full frozen G05exact search/table/heuristic observations and controls",
            "full_acceptance": False,
        },
        1200,
    )
    controls = []
    try:
        c.run(
            "producer",
            [
                py,
                "-m",
                "tools.search_semantics",
                "--engine",
                str(engine),
                "--profile",
                str(profile),
                "--expected-profile-sha256",
                PROFILE_SHA256,
                "--output",
                str(producer),
            ],
            240,
        )

        def command(evidence, destination):
            argv = [py, "-m", "verification.search_semantics"]
            for name, path in [
                ("observations", evidence / "observations.jsonl"),
                ("summary", evidence / "SUMMARY.json"),
                ("config", evidence / "CONFIG.json"),
                ("engine", engine),
                ("profile", profile),
                ("output", destination),
            ]:
                argv += ["--" + name, str(path)]
            for name, value in [
                ("engine", sha(engine)),
                ("profile", PROFILE_SHA256),
                ("observations", sha(evidence / "observations.jsonl")),
            ]:
                argv += ["--expected-" + name + "-sha256", value]
            return argv

        c.run("independent", command(producer, output / "independent"), 600)
        positive = json.loads(
            (output / "independent/SEARCH_SEMANTICS.json").read_text()
        )
        assert positive["full_gate"] and positive["categories"]["exact"] > 0
        original = [
            json.loads(row)
            for row in (producer / "observations.jsonl").read_text().splitlines()
        ]
        first = next(i for i, row in enumerate(original) if row["kind"] == "exact")

        def reject(case, argv, reason, maximum=30):
            try:
                c.run(case, argv, maximum)
            except StageFailure as error:
                result = json.loads((output / (case + ".log")).read_text())
                assert error.record["exit"] == 1 and reason in result.get(
                    "reason", ""
                ), (case, result, error.record)
                controls.append(
                    {"case": case, "actual_exit": 1, "reason": result["reason"]}
                )
            else:
                raise AssertionError("search verifier accepted " + case)

        for case in [
            "table-bound",
            "mate-normalization",
            "score",
            "illegal-pv",
            "bool-nodes",
            "disabled-heuristic",
            "sequence",
            "false-count",
            "missing-observation",
        ]:
            evidence = output / ("mutant-" + case)
            shutil.copytree(producer, evidence)
            rows = json.loads(json.dumps(original))
            if case == "table-bound":
                rows[2]["actual"]["entry"]["bound"] = (
                    2 if rows[2]["actual"]["entry"]["bound"] == 1 else 1
                )
            elif case == "mate-normalization":
                rows[3]["actual"]["entry"]["score"] += 1
            elif case == "score":
                rows[first]["actual"]["score"] += 1
            elif case == "illegal-pv":
                rows[first]["actual"]["bestmove"] = "a1a8"
                rows[first]["actual"]["pv"] = ["a1a8"]
            elif case == "bool-nodes":
                rows[first]["actual"]["nodes"] = True
            elif case == "disabled-heuristic":
                rows[first]["actual"]["stats"]["null_cutoffs"] = 1
            elif case == "sequence":
                rows[0]["index"] = True
            elif case == "missing-observation":
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
                "table bound/mate/identity differs"
                if case in ["table-bound", "mate-normalization"]
                else (
                    "minimax value differs"
                    if case == "score"
                    else (
                        "legal root"
                        if case == "illegal-pv"
                        else (
                            "wire integer type differs"
                            if case == "bool-nodes"
                            else (
                                "disabled search heuristic"
                                if case == "disabled-heuristic"
                                else (
                                    "frozen command inventory differs"
                                    if case == "false-count"
                                    else "frozen command schedule differs"
                                )
                            )
                        )
                    )
                )
            )
            reject(case, command(evidence, output / ("replay-" + case)), reason)
        commit = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], text=True, timeout=5
        ).strip()
        bundle = output / "full-bundle"
        inputs = fixture(bundle, root, root, commit)
        shutil.copy2(engine, bundle / "bin/caissa")
        inputs["engine"] = reference(bundle, "bin/caissa")
        for domain in inputs["domains"].values():
            domain["engine_sha256"] = inputs["engine"]["sha256"]
        (bundle / "search").mkdir()
        for src, name in [
            (producer / "CONFIG.json", "CONFIG.json"),
            (producer / "SUMMARY.json", "SUMMARY.json"),
            (producer / "observations.jsonl", "observations.jsonl"),
            (profile, "profile.json"),
        ]:
            shutil.copy2(src, bundle / "search" / name)
        refs = {
            key: reference(bundle, "search/" + name)
            for key, name in [
                ("config", "CONFIG.json"),
                ("summary", "SUMMARY.json"),
                ("observations", "observations.jsonl"),
                ("profile", "profile.json"),
            ]
        }
        domain = inputs["domains"]["G05"]
        domain.update(
            {
                "driver": "search-semantics-v1",
                "search_semantics": refs,
                "artifacts": list(refs.values()),
            }
        )

        def full(destination):
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
                seal(bundle, inputs),
                "--replay-output",
                str(destination),
            ]

        try:
            c.run("full-positive", full(output / "full-replay"), 600)
        except StageFailure as error:
            result = json.loads((output / "full-positive.log").read_text())
            assert (
                error.record["exit"] == 2
                and result["status"] == "incomplete"
                and result["verified_semantic_gates"]["G05"]["full_gate"]
                and len(result["pending_semantic_gates"]) == 15
            ), result
        else:
            raise AssertionError("G05alone manufactured full acceptance")
        reject(
            "full-inside",
            full(bundle / "invalid-output"),
            "preserve the original evidence",
        )
        domain["artifacts"] = list(refs.values())[:-1]
        reject(
            "full-unlisted",
            full(output / "unlisted"),
            "distinct declared raw artifacts",
        )
        domain["artifacts"] = list(refs.values())
        refs["summary"] = refs["config"]
        reject("full-alias", full(output / "alias"), "distinct declared raw artifacts")
        result = {
            "status": "passed",
            "positive": positive,
            "controls": controls,
            "full_acceptance": False,
        }
        atomic(output / "CONTROLS.json", result)
        c.close("passed", result)
    except BaseException as error:
        c.close("failed", {"error": repr(error)})
        raise


if __name__ == "__main__":
    main()
