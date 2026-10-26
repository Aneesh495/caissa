"""A fixed, diagnostic-only trainer interruption with preserved raw boundaries."""

import argparse
import gzip
import hashlib
import json
import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

from tools.campaign_process import Campaign, atomic
from tools.heuristic_study import avoid_decisive_matches
from tools.host_lease import HostLease
from tools.recovery_scope import tree_bytes

FIXTURE = (
    "results/full-model-planning-2026-10-23/fixed-prefix-owner-integration/dataset"
)
FIXTURE_SHA = "51ab630fd7c986efa3010d0f2fc8b6bc1108af0917dc4ec408253a9de21be20e"


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def execute(engine, output):
    avoid_decisive_matches()
    engine, output = Path(engine).resolve(), Path(output).resolve()
    lease = HostLease(Path("runs"))
    campaign = process = None
    try:
        source = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], text=True, timeout=5
        ).strip()
        fixture = Path(FIXTURE)
        if sha(fixture / "DATASET.json") != FIXTURE_SHA:
            raise ValueError("original diagnostic fixture metadata differs")
        wall = time.time()
        config = {
            "schema": "caissa-training-recovery-v1",
            "profile": "training-recovery-component-only",
            "source_commit": source,
            "engine_sha256": sha(engine),
            "dataset_sha256": FIXTURE_SHA,
            "seed": 17,
            "steps": 100,
            "checkpoint_every": 20,
            "neural_weight": 10,
            "classical_contract": 1,
            "maximum_seconds": 180,
            "maximum_output_bytes": 1024**3,
            "minimum_free_bytes": 10 * 1024**3,
            "started_unix": wall,
            "deadline_unix": wall + 180,
            "test_arrays_accessed": False,
            "full_G11_certified": False,
        }

        def guard():
            lease.check()
            if (
                shutil.disk_usage(output).free < 10 * 1024**3
                or tree_bytes(output) > 1024**3
            ):
                raise ValueError("trainer recovery original disk ceiling exhausted")

        campaign = Campaign(output, config, 180, resource_guard=guard)
        runtime = output / "runtime"
        runtime.mkdir()
        dataset = runtime / "dataset"
        dataset.mkdir()
        shutil.copyfile(fixture / "DATASET.json", dataset / "DATASET.json")
        metadata = json.loads((dataset / "DATASET.json").read_text())
        for split in ["train", "validation"]:
            for kind in ["features", "targets"]:
                name = f"{split}-{kind}.npy"
                origin = fixture / name
                target = dataset / name
                if origin.exists():
                    shutil.copyfile(origin, target)
                else:
                    with (
                        gzip.open(str(origin) + ".gz", "rb") as src,
                        target.open("xb") as dst,
                    ):
                        shutil.copyfileobj(src, dst, 1024 * 1024)
                if sha(target) != metadata["files"][name]:
                    raise ValueError("original recovery training input differs")
        baseline = runtime / "baseline"
        campaign.run(
            "baseline-process",
            [
                sys.executable,
                "-m",
                "training.baselines",
                str(dataset),
                str(baseline),
                "--engine",
                str(engine),
            ],
            30,
        )

        def command(folder):
            return [
                sys.executable,
                "-m",
                "training.train",
                str(dataset),
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
                "20",
                "--network-version",
                "3",
                "--neural-weight",
                "10",
                "--baseline-directory",
                str(baseline),
            ]

        whole, recovered = runtime / "whole", runtime / "recovered"
        campaign.run("whole-process", command(whole), 40)
        marker = recovered / "RECOVERY_READY.json"
        before = runtime / "before"
        before.mkdir()
        with (output / "interrupted-process.log").open("wb") as log:
            process = subprocess.Popen(
                command(recovered) + ["--recovery-barrier", str(marker)],
                stdout=log,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
            end = min(time.monotonic() + 30, campaign.deadline)
            while not marker.exists():
                guard()
                if process.poll() is not None or time.monotonic() >= end:
                    raise ValueError(
                        "trainer did not reach its fixed uncommitted boundary"
                    )
                time.sleep(0.01)
            for name in [
                "CONFIG.json",
                "INITIAL.json",
                "initial.pt",
                "CHECKPOINTS.json",
                "observations.jsonl",
                "RECOVERY_READY.json",
            ]:
                shutil.copyfile(recovered / name, before / name)
            pointer = json.loads((before / "CHECKPOINTS.json").read_text())
            generation = pointer["last"]["path"]
            target = before / generation
            target.parent.mkdir(exist_ok=True)
            shutil.copyfile(recovered / generation, target)
            killed = time.monotonic_ns()
            os.killpg(process.pid, signal.SIGKILL)
            code = process.wait(timeout=5)
            reaped = time.monotonic_ns()
            atomic(
                output / "KILL.json",
                {
                    "signal": 9,
                    "actual_exit": code,
                    "pid": process.pid,
                    "signal_monotonic_ns": killed,
                    "reaped_monotonic_ns": reaped,
                    "boundary_sha256": sha(before / "RECOVERY_READY.json"),
                },
            )
            if code != -9:
                raise ValueError(
                    "trainer diagnostic did not actually exit from SIGKILL"
                )
            process = None
        fragment = b'{"step":'
        (before / "injected-torn-tail.bin").write_bytes(fragment)
        with (recovered / "observations.jsonl").open("ab") as stream:
            stream.write(fragment)
            stream.flush()
            os.fsync(stream.fileno())
        campaign.run("resumed-process", command(recovered) + ["--resume"], 40)
        evidence = output / "evidence"
        evidence.mkdir()
        shutil.copyfile(output / "CONFIG.json", evidence / "CONFIG.json")
        shutil.copyfile(output / "KILL.json", evidence / "KILL.json")
        for source_folder, name in [
            (dataset, "dataset"),
            (baseline, "baseline"),
            (whole, "whole"),
            (recovered, "recovered"),
            (before, "before"),
        ]:
            destination = evidence / name
            for path in source_folder.rglob("*"):
                if (
                    not path.is_file()
                    or path.is_symlink()
                    or path.name.endswith(".lock")
                ):
                    continue
                target = destination / path.relative_to(source_folder)
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(path, target)
        atomic(
            evidence / "MANIFEST.json",
            {
                "files": {
                    str(p.relative_to(evidence)): sha(p)
                    for p in sorted(evidence.rglob("*"))
                    if p.is_file()
                }
            },
        )
        campaign.close("recorded", {"full_G11_certified": False})
        return config
    except BaseException as error:
        if campaign is not None:
            campaign.close("failed", {"reason": str(error)})
        raise
    finally:
        if process is not None and process.poll() is None:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait(timeout=5)
        lease.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--engine", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    execute(args.engine, args.output)
    print(json.dumps({"status": "recorded", "full_G11_certified": False}))


if __name__ == "__main__":
    main()
