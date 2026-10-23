"""Rehash numerical forgeries and require independent semantic rejection."""

import argparse
import hashlib
import json
import math
import shutil
import subprocess
import sys
from pathlib import Path


def stats(values):
    ordered = sorted(values)
    at = 0.99 * (len(ordered) - 1)
    lo = math.floor(at)
    hi = math.ceil(at)
    return {
        "mean": math.fsum(values) / len(values),
        "p99": ordered[lo] + (ordered[hi] - ordered[lo]) * (at - lo),
        "max": max(values),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("--engine", required=True, type=Path)
    parser.add_argument("--network", required=True, type=Path)
    parser.add_argument("--checkpoint", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    original = [
        json.loads(line)
        for line in (args.source / "probes.jsonl").read_text().splitlines()
    ]
    config = json.loads((args.source / "CONFIG.json").read_text())
    cases = {
        "integer-observation": "independent saved-byte integer inference differs",
        "floating-observation": "independent saved-parameter floating inference differs",
        "positions-reordered": "probe differs from frozen seeded legal walk",
        "quantized-raw": "independent unclamped quantized inference differs",
        "false-summary": "independent numerical summary differs",
        "false-status": "saved numerical endpoint status differs",
        "full-floor": "full frozen numerical sample or seed differs",
    }
    results = []
    for name, reason in cases.items():
        target = args.output / name
        target.mkdir()
        for file in ["CONFIG.json", "SUMMARY.json", "POSITIONS.fen"]:
            shutil.copy2(args.source / file, target / file)
        rows = [dict(row) for row in original]
        if name == "integer-observation":
            for key in ["native", "scalar", "reference"]:
                rows[0][key] += 1
        elif name == "floating-observation":
            rows[0]["float_raw"] += 1
        elif name == "positions-reordered":
            rows[0], rows[1] = rows[1], rows[0]
            positions = (target / "POSITIONS.fen").read_text().splitlines()
            positions[0], positions[1] = positions[1], positions[0]
            (target / "POSITIONS.fen").write_text("\n".join(positions) + "\n")
        elif name == "quantized-raw":
            rows[0]["reference_raw"] += 1
        for row in rows:
            row["float"] = max(-29871.0, min(29871.0, row["float_raw"]))
            row["error_cp"] = abs(row["float"] - row["native"])
            row["raw_error_cp"] = abs(row["float_raw"] - row["reference_raw"])
        observations = target / "probes.jsonl"
        observations.write_text("".join(json.dumps(row) + "\n" for row in rows))
        summary = json.loads((target / "SUMMARY.json").read_text())
        summary["probes_sha256"] = hashlib.sha256(observations.read_bytes()).hexdigest()
        summary["positions_sha256"] = hashlib.sha256(
            (target / "POSITIONS.fen").read_bytes()
        ).hexdigest()
        summary["float_quantized_cp"] = stats([row["error_cp"] for row in rows])
        summary["raw_float_quantized_cp"] = stats([row["raw_error_cp"] for row in rows])
        if name == "false-summary":
            summary["raw_float_quantized_cp"]["max"] = 0
        if name == "false-status":
            summary["status"] = "failed-frozen-error-bound"
        changed_config = dict(config)
        changed_config["positions_sha256"] = summary["positions_sha256"]
        (target / "SUMMARY.json").write_text(json.dumps(summary) + "\n")
        (target / "CONFIG.json").write_text(json.dumps(changed_config) + "\n")
        command = [
            sys.executable,
            "-m",
            "verification.numerical",
            str(target),
            "--engine",
            str(args.engine),
            "--network",
            str(args.network),
            "--checkpoint",
            str(args.checkpoint),
            "--max-seconds",
            "30",
        ]
        if name == "full-floor":
            rule = {
                "network": {
                    "probes": 100000,
                    "probe_seed": config["probe_seed"],
                    "maximum_float_error_cp": 32,
                    "format": 3,
                    "width": 64,
                    "error_contract": config["error_contract"],
                }
            }
            path = target / "NUMERICAL_RULE_ONLY.json"
            path.write_text(json.dumps(rule) + "\n")
            command += [
                "--require-full",
                "--protocol",
                str(path),
                "--expected-network-sha256",
                hashlib.sha256(args.network.read_bytes()).hexdigest(),
                "--expected-checkpoint-sha256",
                hashlib.sha256(args.checkpoint.read_bytes()).hexdigest(),
            ]
        process = subprocess.run(command, capture_output=True, text=True, timeout=45)
        (target / "rejection.log").write_text(process.stdout + process.stderr)
        response = json.loads(process.stdout)
        if (
            process.returncode != 1
            or response.get("status") != "rejected"
            or reason not in response.get("reason", "")
        ):
            raise ValueError(
                "numerical forgery did not fail for its semantic reason: "
                + name
                + " "
                + process.stdout
                + process.stderr
            )
        results.append(
            {
                "control": name,
                "actual_exit": process.returncode,
                "reason": response["reason"],
            }
        )
    record = {
        "status": "passed",
        "scope": "numerical semantic controls; does not certify full data or learning",
        "controls": results,
        "full_acceptance": False,
    }
    (args.output / "CONTROLS.json").write_text(json.dumps(record, indent=2) + "\n")
    print(json.dumps(record))


if __name__ == "__main__":
    main()
