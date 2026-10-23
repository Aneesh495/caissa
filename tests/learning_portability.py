"""Preserve canonical checkpoints while checking relocation and optional aliases."""

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("--source", type=Path, required=True)
parser.add_argument("--output", type=Path, required=True)
a = parser.parse_args()
a.output.mkdir(parents=True, exist_ok=False)
results = []
for case in ["bad-alias", "missing-generation"]:
    target = a.output / case
    target.mkdir()
    for name in ["seed17", "seed41", "seed73", "selection"]:
        shutil.copytree(a.source / name, target / name, symlinks=True)
    folder = target / "seed17"
    pointer = json.loads((folder / "CHECKPOINTS.json").read_text())
    if case == "bad-alias":
        alias = folder / "last.pt"
        if alias.exists() or alias.is_symlink():
            alias.unlink()
        alternatives = sorted(
            path
            for path in (folder / "checkpoints").glob("step-*.pt")
            if path != folder / pointer["last"]["path"]
        )
        assert alternatives
        alias.symlink_to(alternatives[0].relative_to(folder))
        expected = "checkpoint alias differs from transaction"
    else:
        (folder / pointer["last"]["path"]).unlink()
        expected = pointer["last"]["path"]
    command = [
        sys.executable,
        "-m",
        "verification.learning",
        "--dataset",
        str(a.source / "dataset"),
        "--runs",
        *(str(target / ("seed" + str(seed))) for seed in [17, 41, 73]),
        "--selection",
        str(target / "selection"),
        "--baseline",
        str(a.source / "baseline"),
    ]
    result = subprocess.run(command, capture_output=True, text=True, timeout=120)
    assert result.returncode == 1 and expected in result.stdout, (
        result.stdout + result.stderr
    )
    results.append(
        {
            "case": case,
            "command": command,
            "exit": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr,
        }
    )
(a.output / "CONTROLS.json").write_text(json.dumps(results, indent=2) + "\n")
print(
    json.dumps(
        {
            "status": "passed",
            "cases": len(results),
            "scope": "required generations remain mandatory; present wrong aliases rejected",
        }
    )
)
