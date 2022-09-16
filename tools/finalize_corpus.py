"""Finalize an immutable searched corpus under one separately frozen deadline.

The original producer remains stopped. Every stage uses archived source from a
clean commit; later development cannot alter a running export or verifier.
"""

import argparse
import fcntl
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
from pathlib import Path

from tools.campaign_process import Campaign, atomic
from tools.recovery_scope import RecoveryScope
from verification.acquisition import protocol as read_protocol, prefix, sha
from verification.verify import source_files


def archive_source(root, source, commit, inputs):
    """Extract only frozen tracked code, configuration and model inputs."""
    if source.exists():
        for name, expected in inputs.items():
            if sha(source / name) != expected:
                raise ValueError("archived finalization source changed: " + name)
        return
    with tempfile.TemporaryFile() as stream:
        subprocess.run(
            ["git", "archive", commit, "--", *inputs],
            cwd=root,
            stdout=stream,
            check=True,
            timeout=30,
        )
        stream.seek(0)
        source.mkdir()
        with tarfile.open(fileobj=stream) as archive:
            archive.extractall(source, filter="data")
    for name, expected in inputs.items():
        if sha(source / name) != expected:
            raise ValueError("source archive differs from frozen input: " + name)


def execute(args):
    root = Path.cwd().resolve()
    corpus, dataset, output = (
        args.corpus.resolve(),
        args.dataset.resolve(),
        args.output.resolve(),
    )
    rule = read_protocol(args.protocol, args.expected_protocol_sha256)
    if str(output.relative_to(root)) != rule["campaign_output"]:
        raise ValueError("changing the output path cannot create a new recovery budget")
    if (
        corpus == dataset
        or output.is_relative_to(dataset)
        or dataset.is_relative_to(output)
    ):
        raise ValueError("recovery source, data and owner directories must be separate")
    if args.resume:
        state = json.loads((output / "SCOPE.json").read_text())
        inputs = json.loads((output / "SOURCE_INPUTS.json").read_text())
        commit = inputs["commit"]
    else:
        if subprocess.check_output(["git", "status", "--porcelain"], text=True):
            raise ValueError("commit source and protocol before full finalization")
        commit = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], text=True
        ).strip()
        inputs = {
            "commit": commit,
            "files": {p: sha(root / p) for p in source_files(root)},
        }
    bindings = {
        "protocol_sha256": args.expected_protocol_sha256,
        "pair_manifest_sha256": rule["pair_hash_manifest_sha256"],
        "corpus": str(corpus),
        "dataset": str(dataset),
        "source_commit": commit,
        "workflow_sha256": inputs["files"]["tools/finalize_corpus.py"],
    }
    if sha(__file__) != bindings["workflow_sha256"]:
        raise ValueError(
            "recovery owner code changed; use its archived source to resume"
        )
    from tools.power_guard import PowerGuard

    power = PowerGuard(rule.get("host_policy"))
    scope = RecoveryScope(
        output,
        bindings,
        rule["maximum_wall_seconds"],
        dataset,
        rule["minimum_free_gib"],
        rule["maximum_additional_disk_gib"],
        resume=args.resume,
        maximum_authorized_seconds=86400 if rule["schema"].endswith("v2") else 21600,
        maximum_active_seconds=rule.get("maximum_active_seconds"),
    )
    campaign = None
    corpus_lock = None
    try:
        power.start(output)

        def resource_check():
            scope.check()
            power.check()

        corpus_lock = (corpus / "CORPUS.lock").open("a")
        fcntl.flock(corpus_lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        source = output / "source"
        if not args.resume:
            atomic(output / "SOURCE_INPUTS.json", inputs)
            (output / "inputs").mkdir()
            shutil.copy2(args.protocol, output / "inputs/PROTOCOL.json")
            shutil.copy2(args.pair_manifest, output / "inputs/PAIR_HASHES.jsonl")
        frozen_protocol, pair_manifest = (
            output / "inputs/PROTOCOL.json",
            output / "inputs/PAIR_HASHES.jsonl",
        )
        read_protocol(frozen_protocol, args.expected_protocol_sha256)
        attempts = (
            sorted((output / "attempts").glob("attempt-*"))
            if (output / "attempts").exists()
            else []
        )
        if len(attempts) >= 3:
            raise ValueError("three meaningful recovery attempts already used")
        campaign = Campaign(
            output / "attempts" / f"attempt-{len(attempts)+1:03d}",
            {
                "source_commit": commit,
                "global_deadline_unix": scope.deadline,
                "bindings": bindings,
                "maximum_remaining_seconds": scope.remaining(),
            },
            scope.remaining(),
            absolute_deadline=scope.deadline,
            resource_guard=resource_check,
            maximum_wall_seconds=(
                scope.deadline - time.time() if rule["schema"].endswith("v2") else None
            ),
        )
        archive_source(root, source, commit, inputs["files"])
        scope.check()
        preserved = prefix(
            rule, corpus, pair_manifest, check=scope.check, verify_bytes=True
        )
        atomic(
            output / "PREFIX_CHECK.json",
            {
                "pairs": len(preserved),
                "pair_manifest_sha256": sha(pair_manifest),
                "original_failure_sha256": sha(corpus / "INTERRUPTED.json"),
                "verified_unix": time.time(),
            },
        )
        if not (dataset / "DATASET.json").exists():
            campaign.run(
                "export",
                [
                    sys.executable,
                    "-m",
                    "training.prepare",
                    str(corpus),
                    str(dataset),
                    "--resume",
                ],
                min(7200, scope.remaining()),
                cwd=source,
            )
        scope.check()
        manifest = json.loads((dataset / "DATASET.json").read_text())
        if (
            manifest["splits"]["train"] < 10000000
            or manifest["counts"]["completed_games"] < 100000
        ):
            raise ValueError("exported data does not meet mandatory full floors")
        atomic(
            output / "EXPORTED.json",
            {
                "dataset_sha256": sha(dataset / "DATASET.json"),
                "splits": manifest["splits"],
                "completed_games": manifest["counts"]["completed_games"],
                "original_acquisition_status": "failed-preserved",
                "full_acceptance": False,
            },
        )
        scratch = output / "verification-index"
        scratch.mkdir(exist_ok=True)
        command = [
            sys.executable,
            "-m",
            "verification.dataset",
            str(dataset),
            str(corpus),
            "--require-full",
            "--fixed-prefix-protocol",
            str(frozen_protocol),
            "--expected-prefix-protocol-sha256",
            args.expected_protocol_sha256,
            "--pair-manifest",
            str(pair_manifest),
            "--progress",
            str(output / "INDEPENDENT_PROGRESS.json"),
            "--scratch",
            str(scratch),
            "--retain-index",
            "--max-seconds",
            str(scope.remaining()),
            "--wall-deadline-unix",
            str(scope.deadline),
        ]
        if rule["schema"].endswith("v2"):
            command.extend(
                ["--max-wall-seconds", str(max(1, scope.deadline - time.time()))]
            )
        previous_progress = output / "INDEPENDENT_PROGRESS.json"
        if args.resume and previous_progress.exists():
            from verification.dataset_index import snapshot

            prior = json.loads(previous_progress.read_text())
            if prior.get("index"):
                index = Path(prior["index"]).resolve()
                if not index.is_relative_to(scratch.resolve()):
                    raise ValueError(
                        "independent resume index escaped its original scope"
                    )
                with (index / "OWNER.lock").open("a") as lock:
                    fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    pinned = snapshot(index, scope.check)
                atomic(
                    campaign.output / "INDEX_RESUME.json",
                    {
                        "index": str(index),
                        "stopped_index_sha256": pinned,
                        "source_commit": commit,
                        "global_deadline_unix": scope.deadline,
                    },
                )
                command.extend(
                    [
                        "--resume-index",
                        str(index),
                        "--expected-index-state-sha256",
                        pinned,
                    ]
                )
        campaign.run(
            "independent-data",
            command,
            scope.remaining(),
            cwd=source,
            wall_timeout=(
                max(1, scope.deadline - time.time())
                if rule["schema"].endswith("v2")
                else None
            ),
        )
        verified = json.loads((campaign.output / "independent-data.log").read_text())
        if (
            verified["status"] != "passed"
            or verified["profile"] != "full-data-replay"
            or verified["dataset_sha256"] != sha(dataset / "DATASET.json")
        ):
            raise ValueError(
                "independent complete data replay did not produce the expected identity"
            )
        prefix(rule, corpus, pair_manifest, check=scope.check, verify_bytes=True)
        scope.check()
        report = {
            "status": "passed full original-data finalization and independent reconstruction",
            "source_commit": commit,
            "protocol_sha256": args.expected_protocol_sha256,
            "origin_unix": scope.state["origin_unix"],
            "deadline_unix": scope.deadline,
            "completed_unix": time.time(),
            "dataset_sha256": verified["dataset_sha256"],
            "independent": verified,
            "original_acquisition_status": "failed-preserved",
            "original_failure_sha256": rule["prior_interrupted_sha256"],
            "new_games": 0,
            "full_acceptance": False,
            "scope": "Data domain only; three-seed learning, numerical, strength and remaining project gates are separate",
        }
        atomic(output / "FINALIZATION.json", report)
        campaign.close("passed full original-data domain", report)
        print(json.dumps(report))
        return 0
    except BaseException as error:
        if campaign is not None:
            campaign.close(
                "failed", {"type": type(error).__name__, "reason": str(error)}
            )
        atomic(
            output / "FAILED.json",
            {
                "type": type(error).__name__,
                "reason": str(error),
                "observed_unix": time.time(),
                "original_deadline_unix": scope.deadline,
                "full_acceptance": False,
            },
        )
        raise
    finally:
        try:
            power.close()
        finally:
            if corpus_lock is not None:
                corpus_lock.close()
            scope.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--protocol", type=Path, required=True)
    parser.add_argument("--expected-protocol-sha256", required=True)
    parser.add_argument("--pair-manifest", type=Path, required=True)
    parser.add_argument("--corpus", type=Path, required=True)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    try:
        return execute(args)
    except (
        ValueError,
        OSError,
        subprocess.SubprocessError,
        RuntimeError,
        KeyError,
    ) as error:
        print(
            json.dumps(
                {"status": "failed", "reason": str(error), "full_acceptance": False}
            )
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
