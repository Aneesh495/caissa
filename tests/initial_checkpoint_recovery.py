"""Kill before the first optimizer commit, preserving exact initial provenance."""

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

import numpy as np
import torch
from verification.learning import checkpoint


def equal(a, b):
    if isinstance(a, torch.Tensor):
        return isinstance(b, torch.Tensor) and torch.equal(a, b)
    if isinstance(a, np.ndarray):
        return isinstance(b, np.ndarray) and np.array_equal(a, b)
    if isinstance(a, dict):
        return (
            isinstance(b, dict)
            and a.keys() == b.keys()
            and all(equal(a[k], b[k]) for k in a)
        )
    if isinstance(a, (list, tuple)):
        return (
            type(a) == type(b)
            and len(a) == len(b)
            and all(equal(x, y) for x, y in zip(a, b))
        )
    return a == b


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    interrupted = args.output / "interrupted"
    whole = args.output / "whole"

    def command(folder):
        return [
            sys.executable,
            "-m",
            "training.train",
            str(args.dataset),
            str(folder),
            "--seed",
            "17",
            "--steps",
            "100",
            "--batch",
            "256",
            "--threads",
            "2",
            "--checkpoint-every",
            "100",
            "--network-version",
            "3",
            "--neural-weight",
            "10",
            "--baseline-directory",
            str(args.baseline),
        ]

    with (args.output / "killed.log").open("wb") as log:
        process = subprocess.Popen(
            command(interrupted), stdout=log, stderr=subprocess.STDOUT
        )
        try:
            deadline = time.monotonic() + 30
            while not (interrupted / "INITIAL.json").exists():
                if process.poll() is not None or time.monotonic() >= deadline:
                    raise ValueError(
                        "training exited or failed to publish initial identity before kill"
                    )
                time.sleep(0.001)
            if (interrupted / "CHECKPOINTS.json").exists():
                raise ValueError("forced kill missed the initialization-only window")
            initial = hashlib.sha256(
                (interrupted / "initial.pt").read_bytes()
            ).hexdigest()
            identity = (interrupted / "INITIAL.json").read_bytes()
            if (interrupted / "observations.jsonl").exists():
                shutil.copy2(
                    interrupted / "observations.jsonl",
                    args.output / "observations-before-kill.jsonl",
                )
            process.kill()
            status = process.wait(timeout=5)
            assert status == -9
        finally:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=5)
    for name, folder in [("recovered", interrupted), ("uninterrupted", whole)]:
        with (args.output / (name + ".log")).open("wb") as log:
            subprocess.run(
                command(folder),
                stdout=log,
                stderr=subprocess.STDOUT,
                check=True,
                timeout=60,
            )
    assert (
        hashlib.sha256((interrupted / "initial.pt").read_bytes()).hexdigest() == initial
        and (interrupted / "INITIAL.json").read_bytes() == identity
    )
    a, b = checkpoint(interrupted / "last.pt"), checkpoint(whole / "last.pt")
    keys = [
        "model",
        "optimizer",
        "scheduler",
        "sampler",
        "torch_rng",
        "numpy_rng",
        "python_rng",
        "config",
        "step",
        "updates",
        "initial_hash",
        "current_hash",
        "best_validation",
        "untrained_validation",
    ]
    for key in keys:
        assert equal(a[key], b[key]), key
    bad = args.output / "rehashed-initial"
    bad.mkdir()
    state = checkpoint(interrupted / "initial.pt")
    state["model"]["output.weight"][0, 0] += 1
    torch.save(state, bad / "initial.pt")
    record = json.loads(identity)
    record["sha256"] = hashlib.sha256((bad / "initial.pt").read_bytes()).hexdigest()
    (bad / "INITIAL.json").write_text(json.dumps(record) + "\n")
    shutil.copy2(interrupted / "CONFIG.json", bad / "CONFIG.json")
    result = subprocess.run(command(bad), capture_output=True, text=True, timeout=30)
    (args.output / "rehashed-initial.log").write_text(result.stdout + result.stderr)
    assert (
        result.returncode == 1
        and "saved initialization differs from exact seeded recovery" in result.stderr
    )
    assert not (bad / "CHECKPOINTS.json").exists()
    report = {
        "status": "passed",
        "actual_forced_exit": status,
        "initial_checkpoint_sha256_preserved": initial,
        "initial_identity_bytes_preserved": True,
        "exact_recovered_fields": keys,
        "real_updates_each": 100,
        "rehashed_initial_rejected_exit": result.returncode,
        "test_arrays_opened": False,
        "full_acceptance": False,
    }
    (args.output / "CONTROL.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report))


if __name__ == "__main__":
    main()
