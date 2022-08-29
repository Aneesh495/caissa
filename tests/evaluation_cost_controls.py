"""Rehashed cost evidence must still fail semantic and resource replay."""

import argparse
import copy
import hashlib
import json
import shutil
from pathlib import Path

from verification.evaluation_cost import verify


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--campaign", type=Path, required=True)
    parser.add_argument("--engine", type=Path, required=True)
    parser.add_argument("--network", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    original = [
        json.loads(line)
        for line in (args.campaign / "observations.jsonl").read_text().splitlines()
    ]
    results = []
    for case, reason in [
        ("illegal-pv", "illegal PV"),
        ("changed-budget", "node budget"),
        ("changed-parsed-score", "parsed fields"),
        ("false-completed-fallback", "missing PV"),
        ("fabricated-time-ratio", "cost ratio"),
        ("changed-mode", "mode/resource"),
    ]:
        folder = args.output / case
        folder.mkdir()
        for name in ["CONFIG.json", "SUMMARY.json"]:
            shutil.copy2(args.campaign / name, folder / name)
        rows = copy.deepcopy(original)
        row = next(row for row in rows if "depth" in row["observed"])
        summary = json.loads((folder / "SUMMARY.json").read_text())
        if case == "illegal-pv":
            row["uci"].insert(-1, "info depth 1 score cp 0 nodes 1 pv 0000")
        elif case == "changed-budget":
            row["request"]["go"] = "go nodes 1"
        elif case == "changed-parsed-score":
            row["observed"]["score"] += 1
        elif case == "false-completed-fallback":
            assert row["observed"]["stats"]["completed_depth_nodes"] > 0
            row["uci"] = [
                line for line in row["uci"] if not line.startswith("info depth ")
            ]
        elif case == "fabricated-time-ratio":
            key = next(key for key in summary if key.startswith("paired_"))
            summary[key]["mixture"]["median"] += 0.1
        else:
            config = json.loads((folder / "CONFIG.json").read_text())
            config["modes"][next(iter(config["modes"]))][0] = 99
            (folder / "CONFIG.json").write_text(json.dumps(config) + "\n")
        observations = folder / "observations.jsonl"
        observations.write_text(
            "".join(json.dumps(row, separators=(",", ":")) + "\n" for row in rows)
        )
        summary["observations_sha256"] = hashlib.sha256(
            observations.read_bytes()
        ).hexdigest()
        (folder / "SUMMARY.json").write_text(json.dumps(summary) + "\n")
        try:
            verify(
                folder, args.engine, args.network, Path("config/performance.json"), 120
            )
        except ValueError as error:
            assert reason in str(error), (case, str(error))
            results.append(
                {
                    "case": case,
                    "rejected": True,
                    "reason": str(error),
                    "rehashed_observations_sha256": summary["observations_sha256"],
                }
            )
        else:
            raise AssertionError("rehashed semantic corruption accepted: " + case)
    (args.output / "CONTROLS.json").write_text(
        json.dumps(
            {"status": "passed", "controls": results, "full_acceptance": False},
            indent=2,
        )
        + "\n"
    )
    print(json.dumps(results))


if __name__ == "__main__":
    main()
