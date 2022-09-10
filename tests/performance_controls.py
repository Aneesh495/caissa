"""Actual CLI rejection of rehashed performance, RSS and latency corruptions."""

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--campaign", type=Path, required=True)
    parser.add_argument("--engine", type=Path, required=True)
    parser.add_argument("--network", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--deadline-unix", type=float, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    config = Path("config/performance.json")
    config_sha = hashlib.sha256(config.read_bytes()).hexdigest()
    results = []
    for name, expected in [
        ("illegal-pv", "illegal PV"),
        ("changed-request-budget", "frozen resource"),
        ("fabricated-duration", "actual timestamps"),
        ("invented-rss", "actual ps observation"),
        ("swapped-rss-process", "process or profile"),
        ("changed-native-counter", "actual native output"),
        ("fabricated-throughput", "performance metric"),
        ("missing-search", "sample is incomplete"),
        ("scalar-label-swap", "labels were swapped"),
        ("duplicate-latency", "duplicate or incomplete"),
        ("diagnostic-as-full", "cannot use a diagnostic"),
        ("fake-neural-work", "actual inference"),
        ("oversized-artifact", "before hashing"),
    ]:
        remaining = args.deadline_unix - time.time()
        if remaining <= 1:
            raise TimeoutError(
                "original performance development ceiling exhausted before control"
            )
        folder = args.output / name
        shutil.copytree(args.campaign, folder)
        touched = None
        if name == "oversized-artifact":
            touched = "measurements.jsonl"
            with (folder / touched).open("r+b") as stream:
                stream.truncate(128 * 1024 * 1024 + 1)
        elif name == "fake-neural-work":
            touched = "measurements.jsonl"
            rows = [
                json.loads(line) for line in (folder / touched).read_text().splitlines()
            ]
            row = next(
                row
                for row in rows
                if row["evaluation"] == "neural-native"
                and row["observed"]["stats"]["eval_calls"] > 0
            )
            stat = row["observed"]["stats"]
            stat["neural_evaluations"] = 0
            stat["evaluation_cache_hits"] = stat["eval_calls"]
            for i, line in enumerate(row["uci"]):
                if line.startswith("info string stats "):
                    tokens = line.split()
                    for key in ["neural_evaluations", "evaluation_cache_hits"]:
                        tokens[tokens.index(key) + 1] = str(stat[key])
                    row["uci"][i] = " ".join(tokens)
            (folder / touched).write_text(
                "".join(json.dumps(row, separators=(",", ":")) + "\n" for row in rows)
            )
        elif name in (
            "illegal-pv",
            "changed-request-budget",
            "fabricated-duration",
            "changed-native-counter",
            "missing-search",
        ):
            touched = "measurements.jsonl"
            rows = [
                json.loads(line) for line in (folder / touched).read_text().splitlines()
            ]
            if name == "illegal-pv":
                rows[0]["uci"].insert(-1, "info depth 1 score cp 0 nodes 1 pv 0000")
            elif name == "changed-request-budget":
                rows[0]["request"]["go"] = "go movetime 1"
            elif name == "fabricated-duration":
                rows[0]["roundtrip_ms"] += 1
            elif name == "changed-native-counter":
                rows[0]["observed"]["stats"]["visited_nodes"] += 1
            else:
                rows.pop()
            (folder / touched).write_text(
                "".join(json.dumps(row, separators=(",", ":")) + "\n" for row in rows)
            )
        elif name in ("invented-rss", "swapped-rss-process"):
            touched = "memory.jsonl"
            rows = [
                json.loads(line) for line in (folder / touched).read_text().splitlines()
            ]
            row = next(row for row in rows if row["rss_bytes"] is not None)
            if name == "invented-rss":
                row["rss_bytes"] += 1024
            else:
                row["pid"] += 1
            (folder / touched).write_text(
                "".join(json.dumps(row, separators=(",", ":")) + "\n" for row in rows)
            )
        elif name == "scalar-label-swap":
            touched = "correctness.json"
            rows = json.loads((folder / touched).read_text())
            rows[0]["cases"][0]["scalar"] = True
            (folder / touched).write_text(json.dumps(rows) + "\n")
        elif name == "duplicate-latency":
            touched = "latency.jsonl"
            rows = [
                json.loads(line) for line in (folder / touched).read_text().splitlines()
            ]
            rows[1]["index"] = rows[0]["index"]
            (folder / touched).write_text(
                "".join(json.dumps(row, separators=(",", ":")) + "\n" for row in rows)
            )
        summary = json.loads((folder / "SUMMARY.json").read_text())
        if touched:
            summary["files"][touched] = hashlib.sha256(
                (folder / touched).read_bytes()
            ).hexdigest()
        if name == "fabricated-throughput":
            summary["profiles"][0]["useful_nodes_per_second"] *= 2
        (folder / "SUMMARY.json").write_text(json.dumps(summary) + "\n")
        command = [
            sys.executable,
            "-m",
            "verification.performance",
            str(folder),
            "--engine",
            str(args.engine),
            "--network",
            str(args.network),
            "--config",
            str(config),
            "--expected-config-sha256",
            config_sha,
            "--maximum-seconds",
            str(max(1, int(min(60, remaining)))),
        ]
        if name == "diagnostic-as-full":
            command.append("--require-full")
        result = subprocess.run(
            command, capture_output=True, text=True, timeout=min(65, remaining)
        )
        (folder / "REJECTION.stdout").write_text(result.stdout)
        (folder / "REJECTION.stderr").write_text(result.stderr)
        assert result.returncode == 1, (
            name,
            result.returncode,
            result.stdout[:500],
            result.stderr[:500],
        )
        receipt = json.loads(result.stdout)
        assert expected in receipt["reason"], (name, receipt)
        results.append(
            {
                "case": name,
                "actual_exit": result.returncode,
                "reason": receipt["reason"],
                "rehash": summary["files"].get(touched) if touched else None,
            }
        )
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
