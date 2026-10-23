"""Rehashed semantic mutations must fail the independent transcript checker."""

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("evidence", type=Path)
    parser.add_argument("--engine-sha256", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    original = [
        json.loads(line)
        for line in (args.evidence / "transcript.jsonl").read_text().splitlines()
    ]
    controls = [
        "illegal-bestmove",
        "null-in-playable-position",
        "missing-stop",
        "false-latency",
        "illegal-pv",
        "clock-regression",
    ]
    results = []
    for control in controls:
        root = args.output / control
        root.mkdir()
        for name in ["CONFIG.json", "summary.json"]:
            shutil.copy2(args.evidence / name, root / name)
        rows = [dict(row) for row in original]
        if control in ["illegal-bestmove", "null-in-playable-position"]:
            row = next(
                row for row in rows if row.get("receive", "").startswith("bestmove ")
            )
            row["receive"] = "bestmove " + (
                "a1a8" if control == "illegal-bestmove" else "0000"
            )
        elif control == "missing-stop":
            index = next(
                index for index, row in enumerate(rows) if row.get("send") == "stop"
            )
            del rows[index]
        elif control == "illegal-pv":
            row = next(row for row in rows if " pv " in row.get("receive", ""))
            row["receive"] = row["receive"].split(" pv ", 1)[0] + " pv a1a8"
        elif control == "clock-regression":
            rows[1]["ns"] = rows[0]["ns"] - 1
        path = root / "transcript.jsonl"
        path.write_text(
            "".join(json.dumps(row, separators=(",", ":")) + "\n" for row in rows)
        )
        summary = json.loads((root / "summary.json").read_text())
        summary["transcript_sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
        if control == "false-latency":
            summary["stop_ms"]["p99"] = 0
        (root / "summary.json").write_text(json.dumps(summary) + "\n")
        execution = subprocess.run(
            [
                sys.executable,
                "-m",
                "verification.protocol",
                str(root),
                "--engine-sha256",
                args.engine_sha256,
            ],
            capture_output=True,
            text=True,
            timeout=60,
        )
        (root / "rejection.log").write_text(execution.stdout + execution.stderr)
        if execution.returncode == 0:
            raise ValueError("semantic protocol control was accepted: " + control)
        response = json.loads(execution.stdout)
        if response.get("status") != "rejected":
            raise ValueError(
                "control crashed instead of semantic rejection: " + control
            )
        results.append(
            {
                "control": control,
                "exit": execution.returncode,
                "reason": response["reason"],
            }
        )
    record = {
        "status": "passed",
        "controls": results,
        "profile": "rehashed protocol semantic controls",
        "original_transcript_sha256": hashlib.sha256(
            (args.evidence / "transcript.jsonl").read_bytes()
        ).hexdigest(),
        "full_acceptance": False,
    }
    (args.output / "CONTROLS.json").write_text(json.dumps(record, indent=2) + "\n")
    print(json.dumps(record))


if __name__ == "__main__":
    main()
