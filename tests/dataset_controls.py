"""Rehashed prepared arrays must fail independent original-game reconstruction."""

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path
import numpy as np


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--corpus", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    observed = []
    for case in ("wrong-feature", "wrong-target", "wrong-contributor"):
        folder = args.output / case
        shutil.copytree(
            args.dataset,
            folder,
            ignore=shutil.ignore_patterns("identities.sqlite3*", "PREPARE.lock"),
        )
        if case == "wrong-contributor":
            path = folder / "train-identities.jsonl"
            lines = path.read_text().splitlines()
            row = json.loads(lines[0])
            row["contributors"][0]["count"] += 1
            lines[0] = json.dumps(row)
            path.write_text("\n".join(lines) + "\n")
        else:
            name = (
                "train-features.npy" if case == "wrong-feature" else "train-targets.npy"
            )
            array = np.load(folder / name, mmap_mode="r+")
            if case == "wrong-feature":
                array[0, 0, 0] = (int(array[0, 0, 0]) + 64) % 12288
            else:
                array[0, 0] = float(array[0, 0]) + 0.125
            array.flush()
            del array
            manifest = json.loads((folder / "DATASET.json").read_text())
            manifest["files"][name] = hashlib.sha256(
                (folder / name).read_bytes()
            ).hexdigest()
            (folder / "DATASET.json").write_text(json.dumps(manifest) + "\n")
        command = [
            sys.executable,
            "-m",
            "verification.dataset",
            str(folder),
            str(args.corpus),
        ]
        result = subprocess.run(command, capture_output=True, text=True, timeout=120)
        if result.returncode != 1:
            raise ValueError(
                f"{case} did not reject semantically: {result.stdout} {result.stderr}"
            )
        receipt = json.loads(result.stdout)
        expected = {
            "wrong-feature": "neural features",
            "wrong-target": "prepared target",
            "wrong-contributor": "contributor provenance",
        }[case]
        if expected not in receipt["reason"]:
            raise ValueError(f"{case} failed for unrelated reason: {receipt}")
        observed.append(
            {
                "case": case,
                "rehashed_array": case != "wrong-contributor",
                "subprocess_exit": result.returncode,
                "reason": receipt["reason"],
            }
        )
    (args.output / "CONTROLS.json").write_text(json.dumps(observed, indent=2) + "\n")
    print(json.dumps(observed))


if __name__ == "__main__":
    main()
