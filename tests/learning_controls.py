"""Mutate real saved training artifacts and invoke the independent checker."""

import argparse
import hashlib
import json
import shutil
import struct
import subprocess
import sys
import zlib
from pathlib import Path

import torch
from verification.learning import checkpoint


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def replace_json(path, value):
    temporary = path.with_name(path.name + ".control.tmp")
    temporary.write_text(json.dumps(value, indent=2) + "\n")
    temporary.replace(path)


def replace_state(path, value):
    temporary = path.with_name(path.name + ".control.tmp")
    torch.save(value, temporary)
    temporary.replace(path)


def rewrite_pointer(folder, role, state):
    pointer = json.loads((folder / "CHECKPOINTS.json").read_text())
    relative = pointer[role]["path"]
    path = folder / relative
    replace_state(path, state)
    for name in ["last", "best"]:
        if pointer[name]["path"] == relative:
            pointer[name]["sha256"] = digest(path)
    replace_json(folder / "CHECKPOINTS.json", pointer)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument(
        "--dataset", type=Path, default=Path("data/diagnostic-v2-final-screened")
    )
    parser.add_argument(
        "--baseline", type=Path, default=Path("runs/small-classical-baselines")
    )
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    results = []
    cases = [
        ("validation-loss", "independent saved-checkpoint validation loss differs"),
        ("sampler-state", "saved sampler state differs"),
        ("optimizer-step", "optimizer step provenance differs"),
        ("exported-weight", "selected export weights differ"),
    ]
    for case, reason in cases:
        target = args.output / case
        # Each mutation replaces a destination path before writing, preserving the
        # original immutable run even on filesystems with copied hard links.
        target.mkdir()
        for name in ["seed17", "seed41", "seed73", "selection"]:
            shutil.copytree(args.source / name, target / name, symlinks=True)
        selection_path = target / "selection" / "SELECTION.json"
        selection = json.loads(selection_path.read_text())
        for row in selection["all_seeds"]:
            row["folder"] = str(target / ("seed" + str(row["seed"])))
        selection["selected"]["folder"] = str(
            target / ("seed" + str(selection["selected"]["seed"]))
        )
        folder = target / "seed17"
        if case == "validation-loss":
            path = folder / "observations.jsonl"
            rows = [json.loads(line) for line in path.read_text().splitlines()]
            rows[-1]["validation_quantized"] -= 0.05
            path.write_text("".join(json.dumps(row) + "\n" for row in rows))
        elif case in ["sampler-state", "optimizer-step"]:
            state = checkpoint(folder / "last.pt")
            if case == "sampler-state":
                state["sampler"]["state"]["state"] += 1
            else:
                state["optimizer"]["state"][0]["step"] -= 1
            rewrite_pointer(folder, "last", state)
        else:
            path = target / "selection" / "selected.cai"
            raw = bytearray(path.read_bytes())
            old = struct.unpack_from("<h", raw, 120)[0]
            struct.pack_into("<h", raw, 120, old + 1 if old < 32767 else old - 1)
            struct.pack_into("<I", raw, 112, zlib.crc32(raw[120:]))
            path.write_bytes(raw)
            selection["network"]["sha256"] = digest(path)
            selection["network"]["crc32"] = zlib.crc32(raw[120:])
        replace_json(selection_path, selection)
        command = [
            sys.executable,
            "-m",
            "verification.learning",
            "--dataset",
            str(args.dataset),
            "--runs",
            *(str(target / ("seed" + str(seed))) for seed in [17, 41, 73]),
            "--selection",
            str(target / "selection"),
            "--baseline",
            str(args.baseline),
        ]
        execution = subprocess.run(command, capture_output=True, text=True, timeout=180)
        (target / "verifier.stdout").write_text(execution.stdout)
        (target / "verifier.stderr").write_text(execution.stderr)
        if execution.returncode != 1 or reason not in execution.stdout:
            raise ValueError(
                "control did not reject for the intended semantic reason: "
                + case
                + "\n"
                + execution.stdout
                + execution.stderr
            )
        results.append(
            {
                "case": case,
                "command": command,
                "exit": execution.returncode,
                "expected_reason": reason,
                "actual": execution.stdout.strip(),
            }
        )
        print(json.dumps(results[-1]), flush=True)
    (args.output / "CONTROLS.json").write_text(json.dumps(results, indent=2) + "\n")


if __name__ == "__main__":
    main()
