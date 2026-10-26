"""Interrupt only preparation of the original published 56-pair diagnostic."""

import argparse
import contextlib
import hashlib
import json
import os
import shutil
import signal
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

from tools.campaign_process import Campaign, atomic
from tools.heuristic_study import avoid_decisive_matches
from tools.host_lease import HostLease
from tools.recovery_scope import tree_bytes

FIXTURE = Path("results/full-model-planning-2026-10-23/fixed-prefix-owner-integration")
CORPUS = "818eb731b568d5b7526f20f8b374e516e28b4dd5e48431333ddffdab68ce493e"
DATASET = "51ab630fd7c986efa3010d0f2fc8b6bc1108af0917dc4ec408253a9de21be20e"
PAIRS = "b56c15c47d789e3a1d0a07329b2e6eaa9f89e4d3fe3b040b63de7e59cb8f63d4"
EXPORTS = {
    "DATASET.json",
    "SOURCE_PAIRS.json",
    *{
        f"{s}-{k}"
        for s in ["train", "validation", "test"]
        for k in ["features.npy", "targets.npy", "identities.jsonl"]
    },
}


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def execute(output):
    avoid_decisive_matches()
    output = Path(output).resolve()
    lease = HostLease(Path("runs"))
    process = campaign = None
    try:
        source = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], text=True, timeout=5
        ).strip()
        if subprocess.check_output(
            ["git", "status", "--porcelain"], text=True, timeout=10
        ):
            raise ValueError("commit data recovery source before collecting evidence")
        for path, expected in [
            (FIXTURE / "corpus/CONFIG.json", CORPUS),
            (FIXTURE / "dataset/DATASET.json", DATASET),
            (FIXTURE / "dataset/SOURCE_PAIRS.json", PAIRS),
        ]:
            if sha(path) != expected:
                raise ValueError("original data recovery input differs")
        started = time.time()
        config = {
            "schema": "caissa-data-recovery-v1",
            "profile": "data-recovery-component-only",
            "source_commit": source,
            "corpus_config_sha256": CORPUS,
            "original_dataset_sha256": DATASET,
            "original_source_pairs_sha256": PAIRS,
            "pairs": 56,
            "committed_sources": 32,
            "uncommitted_sources": 52,
            "maximum_seconds": 120,
            "maximum_output_bytes": 1024**3,
            "minimum_free_bytes": 10 * 1024**3,
            "started_unix": started,
            "deadline_unix": started + 120,
            "full_G11_certified": False,
        }

        def guard():
            lease.check()
            if (
                time.time() >= config["deadline_unix"]
                or time.monotonic() >= campaign.deadline
            ):
                raise TimeoutError(
                    "original data recovery diagnostic deadline exhausted"
                )
            if (
                shutil.disk_usage(output).free < 10 * 1024**3
                or tree_bytes(output) > 1024**3
            ):
                raise ValueError("data recovery diagnostic disk ceiling exhausted")

        campaign = Campaign(output, config, 120, resource_guard=guard)
        runtime = output / "runtime"
        corpus = runtime / "corpus"
        (corpus / "000000").mkdir(parents=True)
        shutil.copyfile(FIXTURE / "corpus/CONFIG.json", corpus / "CONFIG.json")
        entries = json.loads((FIXTURE / "dataset/SOURCE_PAIRS.json").read_bytes())
        for entry in entries:
            guard()
            name = f"000000/{entry['pair']:09d}.json"
            shutil.copyfile(FIXTURE / "corpus" / name, corpus / name)
            if sha(corpus / name) != entry["sha256"]:
                raise ValueError("original published game pair differs")
        command = [sys.executable, "-B", "-m", "training.prepare", str(corpus)]
        whole, recovered = runtime / "whole", runtime / "recovered"
        campaign.run(
            "whole-process",
            command + [str(whole)],
            45,
            env=lease.environment(),
            pass_fds=(lease.stream.fileno(),),
        )
        ready = recovered / "RECOVERY_READY.json"
        with (output / "interrupted-process.log").open("w") as log:
            process = subprocess.Popen(
                command + [str(recovered), "--recovery-barrier", str(ready)],
                stdout=log,
                stderr=subprocess.STDOUT,
                start_new_session=True,
                env=lease.environment(),
                pass_fds=(lease.stream.fileno(),),
            )
            while not ready.exists():
                guard()
                if process.poll() is not None:
                    raise ValueError(
                        "data preparer exited before its uncommitted boundary"
                    )
                time.sleep(0.005)
            boundary = output / "boundary"
            boundary.mkdir()
            # The writer is paused after its SQL changes and before COMMIT.
            # A separate connection must still see the 32-source generation.
            with contextlib.closing(
                sqlite3.connect(
                    f"file:{recovered / 'identities.sqlite3'}?mode=ro", uri=True
                )
            ) as connection:
                if (
                    connection.execute("SELECT count(*) FROM sources").fetchone()[0]
                    != 32
                ):
                    raise ValueError("uncommitted SQL work escaped the transaction")
            for name in [
                "RECOVERY_READY.json",
                "PREPARE_PROGRESS.json",
                "identities.sqlite3",
                "identities.sqlite3-wal",
                "identities.sqlite3-shm",
            ]:
                shutil.copyfile(recovered / name, boundary / name)
            sent = time.monotonic_ns()
            os.killpg(process.pid, signal.SIGKILL)
            actual_exit = process.wait(timeout=5)
            killed = {
                "signal": int(signal.SIGKILL),
                "actual_exit": actual_exit,
                "pid": process.pid,
                "signal_sent_ns": sent,
                "reaped_ns": time.monotonic_ns(),
            }
            if actual_exit != -int(signal.SIGKILL):
                raise ValueError("data recovery did not observe an actual SIGKILL")
            atomic(output / "KILL.json", killed)
            process = None
        campaign.run(
            "recovered-process",
            command + [str(recovered), "--resume"],
            45,
            env=lease.environment(),
            pass_fds=(lease.stream.fileno(),),
        )
        evidence = output / "evidence"
        evidence.mkdir()
        atomic(evidence / "CONFIG.json", config)
        shutil.copyfile(output / "KILL.json", evidence / "KILL.json")
        shutil.copyfile(
            FIXTURE / "dataset/DATASET.json", evidence / "ORIGINAL_DATASET.json"
        )
        shutil.copyfile(
            FIXTURE / "dataset/SOURCE_PAIRS.json",
            evidence / "ORIGINAL_SOURCE_PAIRS.json",
        )
        shutil.copytree(boundary, evidence / "boundary")
        shutil.copytree(corpus, evidence / "corpus")
        (evidence / "config").mkdir()
        for name in ["studies.json", "strength-openings.json"]:
            shutil.copyfile(Path("config") / name, evidence / "config" / name)
        for name, folder in [("whole", whole), ("recovered", recovered)]:
            (evidence / name).mkdir()
            for export in EXPORTS:
                shutil.copyfile(folder / export, evidence / name / export)
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
        campaign.close(
            "produced original data recovery evidence",
            {"strength_games": 0, "new_training": False, "full_G11_certified": False},
        )
        return {
            "status": "produced",
            "evidence": str(evidence),
            "full_G11_certified": False,
        }
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
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(execute(args.output)))


if __name__ == "__main__":
    main()
