"""Rehashed runtime mutations through the independent read-only CLI."""

import argparse
import hashlib
import json
import shutil
import sys
import zipfile
from pathlib import Path

from tools.campaign_process import Campaign, StageFailure


def write(path, value):
    path.write_text(json.dumps(value, separators=(",", ":"), allow_nan=False) + "\n")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    owner = Campaign(
        args.output,
        {
            "purpose": "Read-only native runtime negative controls",
            "full_acceptance": False,
        },
        180,
    )
    output, py = args.output.resolve(), sys.executable
    manifest = json.loads((args.evidence / "MANIFEST.json").read_text())
    reports = []
    try:
        for host in ["linux", "macos"]:
            actor = manifest["platforms"][host]
            archive = args.evidence / host / "RAW.zip"
            assert (
                hashlib.sha256(archive.read_bytes()).hexdigest()
                == actor["artifact_sha256"]
            )
            destination = output / host
            destination.mkdir()
            with zipfile.ZipFile(archive) as raw:
                assert (
                    sum(item.file_size for item in raw.infolist()) <= 64 * 1024 * 1024
                )
                for name in [
                    "CONFIG.json",
                    "SUMMARY.json",
                    "SESSIONS.json",
                    "observations.jsonl",
                ]:
                    entry = next(
                        n for n in raw.namelist() if n.endswith("/runtime/" + name)
                    )
                    (destination / name).write_bytes(raw.read(entry))

            def command(root):
                return [
                    py,
                    "-m",
                    "verification.deferred_neural",
                    str(root),
                    "--expected-engine-sha256",
                    actor["engine_sha256"],
                    "--expected-reference-sha256",
                    actor["reference_sha256"],
                ]

            owner.run(host + "-positive", command(destination), 30)
            positive = json.loads((output / (host + "-positive.log")).read_text())
            assert (
                positive["queries"] == 720
                and positive["exact_triplets"] == 240
                and positive["full_acceptance"] is False
            )
            if host == "macos":
                continue
            for case, reason in [
                ("partial", "complete query inventory differs"),
                ("counter-duplicate", "repeated or invalid counter"),
                ("illegal-pv", "illegal PV"),
                ("timestamp", "wall duration differs"),
                ("order", "randomized paired inventory differs"),
                ("mixture", "configured evaluator or resources differ"),
                ("model", "externally pinned actor differs"),
                ("ratio", "reconstructed timing ratios differ"),
            ]:
                mutant = output / case
                shutil.copytree(destination, mutant)
                rows = [
                    json.loads(line)
                    for line in (mutant / "observations.jsonl").read_text().splitlines()
                ]
                if case == "partial":
                    rows.pop()
                elif case == "counter-duplicate":
                    row = rows[0]
                    row["lines"] = [
                        (
                            line.replace(" qnodes ", " visited_nodes ")
                            if line.startswith("info string stats ")
                            else line
                        )
                        for line in row["lines"]
                    ]
                elif case == "illegal-pv":
                    row = rows[0]
                    offset = next(
                        i
                        for i, line in enumerate(row["lines"])
                        if line.startswith("info depth ")
                    )
                    before, variation = row["lines"][offset].split(" pv ")
                    words = variation.split()
                    words[0] = "a1a8"
                    row["lines"][offset] = before + " pv " + " ".join(words)
                elif case == "timestamp":
                    rows[0]["roundtrip_ms"] += 1
                elif case == "order":
                    rows[0]["order"] = rows[0]["order"][::-1]
                elif case == "mixture":
                    sessions = json.loads((mutant / "SESSIONS.json").read_text())
                    sessions[0]["commands"] = [
                        c.replace("Neural Weight value 0", "Neural Weight value 10")
                        for c in sessions[0]["commands"]
                    ]
                    write(mutant / "SESSIONS.json", sessions)
                elif case == "model":
                    config = json.loads((mutant / "CONFIG.json").read_text())
                    config["network_sha256"] = "f" * 64
                    write(mutant / "CONFIG.json", config)
                elif case == "ratio":
                    summary = json.loads((mutant / "SUMMARY.json").read_text())
                    summary["results"][0]["median_lazy_to_archived_wall_ratio"] += 0.01
                    write(mutant / "SUMMARY.json", summary)
                (mutant / "observations.jsonl").write_text(
                    "".join(
                        json.dumps(row, separators=(",", ":")) + "\n" for row in rows
                    )
                )
                # Rehash every ordinary artifact after the semantic mutation.
                write(
                    mutant / "REHASHED.json",
                    {
                        p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                        for p in mutant.iterdir()
                        if p.is_file()
                    },
                )
                try:
                    owner.run(case, command(mutant), 30)
                except StageFailure as error:
                    result = json.loads((output / (case + ".log")).read_text())
                    assert error.record["exit"] == 1 and reason in result["reason"], (
                        case,
                        result,
                    )
                    reports.append(
                        {
                            "case": case,
                            "actual_exit": error.record["exit"],
                            "reason": result["reason"],
                        }
                    )
                else:
                    raise AssertionError(
                        "independent runtime verifier accepted " + case
                    )
        result = {
            "status": "passed",
            "positive_native_queries": 1440,
            "controls": reports,
            "scope": "Raw native bytes only; no engine execution or new timing observations",
            "full_acceptance": False,
        }
        write(output / "CONTROLS.json", result)
        owner.close("passed", result)
    except BaseException as error:
        owner.close("failed", {"error": repr(error)})
        raise


if __name__ == "__main__":
    main()
