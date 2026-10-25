"""Continue the existing corpus into separately bounded learning and strength.

This owns scheduling, never a replacement data or experiment authorization.
Each domain keeps its original output, locks, source archive and deadlines.
"""

import argparse
import fcntl
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

from tools.campaign_process import Campaign, StageFailure, atomic
from tools.full_learning import frozen_rule
from tools.finalize_corpus import archive_source
from verification.acquisition import sha
from verification.protocol import read_json
from verification.verify import source_files

DATA = Path("runs/searched-full-v3-finalization-v2")
DATASET = Path("data/searched-full-v3-prepared")
DRAFT = Path("config/protocol-v3.proposed.json")
PROTOCOL = Path("config/protocol-v3.json")
OUTPUT = Path("runs/project-continuation-v1")
MODEL = Path("runs/searched-full-model-v3")
MAXIMUM_WALL_SECONDS = 3 * 86400


def require(value, reason):
    if not value:
        raise ValueError(reason)


def finalized(rule, receipt, dataset_sha):
    require(
        receipt.get("status")
        == "passed full original-data finalization and independent reconstruction"
        and receipt.get("protocol_sha256")
        == rule["data"]["finalization_protocol_sha256"]
        and receipt.get("dataset_sha256") == dataset_sha
        and receipt.get("independent", {}).get("profile") == "full-data-replay",
        "the existing corpus has no matching complete independent pass",
    )


def completion(kind, path, protocol_sha, exit_code=None):
    receipt = read_json(path.read_text())
    statuses = {
        "model": {
            "completed planned model domain campaign",
            "completed planned model domain campaign with failed gates",
        },
        "strength": {
            "completed fixed full strength sample",
            "completed fixed full strength sample with failed gate",
        },
    }
    require(
        receipt.get("status") in statuses[kind]
        and receipt.get("protocol_sha256") == protocol_sha
        and receipt.get("full_acceptance") is False
        and type(receipt.get("failed_domains")) is list,
        "domain has no complete matching receipt: " + kind,
    )
    if kind == "model":
        require(
            receipt.get("seeds") == [17, 41, 73]
            and receipt.get("updates_per_seed") == 20000
            and receipt.get("test_model_metrics_used_for_selection") is False,
            "three complete seeds and validation-only selection are absent",
        )
    failed = bool(receipt["failed_domains"])
    require(
        ("with failed" in receipt["status"]) == failed, "domain failure flags disagree"
    )
    if exit_code is not None:
        require(
            exit_code == (2 if failed else 0),
            "domain exit differs from completed receipt",
        )
    return receipt


def archived_command(module, arguments, directory):
    """A resumed owner imports its original archived workflow, even after edits."""
    source = directory / "source" if (directory / "SCOPE.json").exists() else Path.cwd()
    require(source.is_dir(), "original owner source is missing")
    launcher = "import runpy,sys;sys.path.insert(0,sys.argv.pop(1));runpy.run_module(sys.argv.pop(1),run_name='__main__')"
    return [
        sys.executable,
        "-P",
        "-c",
        launcher,
        str(source.resolve()),
        module,
        *map(str, arguments),
    ]


def wait_for_data(deadline, output):
    while True:
        require(
            time.time() < deadline,
            "continuation wall ceiling exhausted during dependency wait",
        )
        if (DATA / "FINALIZATION.json").exists():
            return
        progress = DATA / "INDEPENDENT_PROGRESS.json"
        observed = read_json(progress.read_text()) if progress.exists() else {}
        atomic(
            output / "PROGRESS.json",
            {
                "phase": "waiting-for-existing-full-data-replay",
                "observed": observed,
                "unix": time.time(),
                "full_acceptance": False,
            },
        )
        with (DATA / "OWNER.lock").open("a") as owner:
            try:
                fcntl.flock(owner.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                pass
            else:
                if not (DATA / "FINALIZATION.json").exists():
                    raise ValueError(
                        "existing data owner stopped without a full pass; inspect its retained failure and remaining scope"
                    )
                return
        # The producer owns stall recovery. Its atomic counters and live process
        # remain visible to the heartbeat; waiting cannot restart acquisition.
        time.sleep(min(15, max(0, deadline - time.time())))


def freeze(campaign, draft):
    receipt = DATA / "FINALIZATION.json"
    dataset_sha = sha(DATASET / "DATASET.json")
    finalized(draft, read_json(receipt.read_text()), dataset_sha)
    rule = read_json(json.dumps(draft))
    rule["status"] = "frozen"
    rule["data"]["dataset_sha256"] = dataset_sha
    rule["data"]["finalization_sha256"] = sha(receipt)
    status = subprocess.check_output(
        ["git", "status", "--porcelain"], text=True, timeout=15
    )
    require(
        status
        in (
            "",
            "?? config/protocol-v3.json\n",
            " M config/protocol-v3.json\n",
            "A  config/protocol-v3.json\n",
        ),
        "commit independent work before freezing the full model source",
    )
    if PROTOCOL.exists():
        require(
            read_json(PROTOCOL.read_text()) == rule,
            "a different frozen v3 protocol already exists",
        )
    else:
        atomic(PROTOCOL, rule)
    protocol_sha = sha(PROTOCOL)
    frozen_rule(PROTOCOL, protocol_sha)
    dirty = subprocess.check_output(
        ["git", "status", "--porcelain"], text=True, timeout=15
    )
    if dirty:
        campaign.run("freeze-stage", ["git", "add", "--", str(PROTOCOL)], 30)
        campaign.run("freeze-check", ["git", "diff", "--cached", "--check"], 30)
        campaign.run(
            "freeze-commit",
            [
                "git",
                "commit",
                "-m",
                "Freeze full searched-data learning and strength protocol",
            ],
            60,
        )
    campaign.run("freeze-push", ["git", "push", "origin", "main"], 60)
    commit = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], text=True, timeout=15
    ).strip()
    remote = subprocess.check_output(
        ["git", "ls-remote", "origin", "refs/heads/main"], text=True, timeout=30
    ).split()[0]
    require(commit == remote, "frozen full protocol remote parity failed")
    atomic(
        OUTPUT / "FROZEN.json",
        {
            "protocol_sha256": protocol_sha,
            "commit": commit,
            "data_finalization_sha256": sha(receipt),
        },
    )
    return rule, protocol_sha


def execute(args):
    root = Path.cwd()
    if args.resume:
        inputs = read_json((OUTPUT / "SOURCE_INPUTS.json").read_text())
    else:
        require(
            not subprocess.check_output(
                ["git", "status", "--porcelain"], text=True, timeout=15
            ),
            "commit scheduling source before starting continuation",
        )
        inputs = {
            "commit": subprocess.check_output(
                ["git", "rev-parse", "HEAD"], text=True, timeout=15
            ).strip(),
            "files": {p: sha(root / p) for p in source_files(root)},
        }
    comparator = OUTPUT / "bin/stockfish"
    comparator_source = comparator if args.resume else args.stockfish
    require(
        comparator_source.stat().st_size <= 256 * 1024**2,
        "external comparator input byte ceiling",
    )
    comparator_sha = sha(comparator_source)
    require(
        comparator_sha == read_json(DRAFT.read_text())["matches"]["stockfish_sha256"],
        "external comparator differs from prospective Stockfish identity",
    )
    OUTPUT.mkdir(parents=True, exist_ok=args.resume)
    lock = (OUTPUT / "OWNER.lock").open("a")
    fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    bindings = {
        "workflow_sha256": sha(__file__),
        "draft_sha256": sha(DRAFT),
        "existing_data_scope_sha256": sha(DATA / "SCOPE.json"),
        "maximum_wall_seconds": MAXIMUM_WALL_SECONDS,
        "external_comparator_sha256": comparator_sha,
        "source_inputs_sha256": hashlib.sha256(
            json.dumps(inputs, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest(),
    }
    scope_path = OUTPUT / "SCOPE.json"
    if args.resume:
        scope = read_json(scope_path.read_text())
        require(
            scope["bindings"] == bindings
            and scope["deadline_unix"] == scope["origin_unix"] + MAXIMUM_WALL_SECONDS,
            "continuation inputs or original ceiling changed",
        )
    else:
        now = time.time()
        scope = {
            "bindings": bindings,
            "origin_unix": now,
            "deadline_unix": now + MAXIMUM_WALL_SECONDS,
            "scope": "Scheduling only; never extends any child domain deadline",
            "full_acceptance": False,
        }
        atomic(scope_path, scope)
    require(
        scope["origin_unix"] - 5 <= time.time() < scope["deadline_unix"],
        "original continuation wall ceiling exhausted or clock reversed",
    )
    attempts = sorted((OUTPUT / "attempts").glob("attempt-*"))
    require(len(attempts) < 3, "continuation maximum three recovery attempts used")
    campaign = Campaign(
        OUTPUT / "attempts" / f"attempt-{len(attempts)+1:03d}",
        bindings,
        scope["deadline_unix"] - time.time(),
        absolute_deadline=scope["deadline_unix"],
    )
    try:
        if not args.resume:
            atomic(OUTPUT / "SOURCE_INPUTS.json", inputs)
        archive_source(root, OUTPUT / "source", inputs["commit"], inputs["files"])
        comparator.parent.mkdir(exist_ok=True)
        if not comparator.exists():
            shutil.copy2(comparator_source, comparator)
        require(sha(comparator) == comparator_sha, "saved external comparator changed")
        wait_for_data(scope["deadline_unix"], OUTPUT)
        rule, protocol_sha = freeze(campaign, read_json(DRAFT.read_text()))

        def domain(name, module, directory, receipt, arguments, kind, active, wall):
            atomic(
                OUTPUT / "PROGRESS.json",
                {
                    "phase": name,
                    "output": str(directory),
                    "unix": time.time(),
                    "full_acceptance": False,
                },
            )
            if receipt.exists():
                return completion(kind, receipt, protocol_sha)
            if (directory / "SCOPE.json").exists():
                arguments += ["--resume"]
            code = 0
            try:
                campaign.run(
                    name,
                    archived_command(module, arguments, directory),
                    active,
                    wall_timeout=wall,
                )
            except StageFailure as error:
                # Only an actual finished domain with its audited negative
                # endpoint may continue. Timeouts, crashes and corrupt inputs
                # cannot turn into a scientific negative or a completed phase.
                require(
                    error.record["exit"] == 2
                    and error.record["reason"] == "nonzero-exit",
                    "domain did not finish: " + name,
                )
                code = 2
            return completion(kind, receipt, protocol_sha, code)

        shared = [
            "--protocol",
            PROTOCOL.resolve(),
            "--expected-protocol-sha256",
            protocol_sha,
        ]
        model = domain(
            "full-model",
            "tools.full_learning",
            MODEL,
            MODEL / "MODEL_CAMPAIGN.json",
            [
                *shared,
                "--dataset",
                DATASET.resolve(),
                "--finalization",
                (DATA / "FINALIZATION.json").resolve(),
                "--output",
                MODEL.resolve(),
            ],
            "model",
            21600,
            86400,
        )
        failures = model["failed_domains"].copy()
        results = {"model": sha(MODEL / "MODEL_CAMPAIGN.json")}
        for kind in ("neural", "external"):
            directory = Path("runs/full-" + kind + "-strength-v3")
            arguments = [
                kind,
                *shared,
                "--model-campaign",
                MODEL.resolve(),
                "--expected-model-campaign-sha256",
                results["model"],
            ]
            if kind == "external":
                arguments += ["--stockfish", comparator.resolve()]
            receipt = domain(
                "full-" + kind,
                "tools.full_strength",
                directory,
                directory / "STRENGTH_CAMPAIGN.json",
                arguments,
                "strength",
                43200,
                43200,
            )
            failures += receipt["failed_domains"]
            results[kind] = sha(directory / "STRENGTH_CAMPAIGN.json")
        result = {
            "status": "planned full learning and strength observations finished",
            "receipt_sha256": results,
            "failed_domains": failures,
            "protocol_sha256": protocol_sha,
            "absolute_elo": None,
            "full_acceptance": False,
            "remaining": "Final systems, browser, independent whole-project verification and release gates remain required",
        }
        atomic(OUTPUT / "CONTINUATION.json", result)
        atomic(OUTPUT / "PROGRESS.json", result)
        campaign.close(result["status"], result)
    except BaseException as error:
        failure = {
            "type": type(error).__name__,
            "reason": str(error),
            "unix": time.time(),
            "original_deadline_unix": scope["deadline_unix"],
            "full_acceptance": False,
        }
        atomic(OUTPUT / "FAILED.json", failure)
        campaign.close(
            "stopped; retained failure requires diagnosis within original child scope",
            failure,
        )
        raise
    finally:
        lock.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--stockfish", type=Path, required=True)
    args = parser.parse_args()
    os.environ["PATH"] = "/opt/homebrew/bin:" + os.environ.get("PATH", "")
    execute(args)


if __name__ == "__main__":
    main()
