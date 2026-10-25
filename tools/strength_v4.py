"""New derived-actor strength sequence with immutable originals and ceilings.

This owner never calls the old learning owner or edits its receipt. Existing
completed match domains are read to advance the sequence, never executed again.
"""

import argparse
import fcntl
import json
import os
import platform
import shutil
import subprocess
import sys
import time
from pathlib import Path

from tools.campaign_process import Campaign, StageFailure, atomic
from tools.finalize_corpus import archive_source
from tools.full_strength import HostGuard, process_rows
from tools.power_guard import PowerGuard
from tools.recovery_scope import RecoveryScope
from tools.strength_v4_profile import (
    COMPILED_SOURCE,
    ENGINE,
    NETWORK,
    PARENT_DEADLINE,
    SCOPES,
    configuration,
    document,
    frozen_profile,
    lineage,
    require,
    sha,
)
from verification.source import PRODUCT, inventory


def context(root, args):
    model = root / "runs/searched-full-model-v3"
    # Prefer existing externally pinned source when moving to the next domain
    # or resuming. A newer checkout cannot silently replace queued actor code.
    existing = None
    for kind in ["neural", "external"]:
        candidate = root / SCOPES[kind] / "SOURCE_INPUTS.json"
        if candidate.exists():
            existing = candidate
            break
    if existing is None:
        require(not args.resume, "v4 has no original scope to resume")
        require(
            not subprocess.check_output(
                ["git", "status", "--porcelain"], cwd=root, text=True, timeout=10
            ),
            "commit v4 source/profile before timed matches",
        )
        commit = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=root, text=True, timeout=5
        ).strip()
        inputs = {
            "commit": commit,
            "files": {
                blob.name: sha(root / blob.name)
                for blob in inventory(root, commit, PRODUCT)
            },
        }
        source_root = root
    else:
        inputs = document(existing)
        commit = inputs["commit"]
        source_root = existing.parent / "source"
        require(source_root.is_dir(), "v4 original source archive missing")
        require(
            args.resume,
            "v4 already started; continue with --resume and original archives",
        )
        for name, digest in inputs["files"].items():
            require(
                sha(source_root / name) == digest,
                "v4 original archived source changed: " + name,
            )
        if Path(__file__).resolve() != source_root / "tools/strength_v4.py":
            # Re-enter all imports from the original archive before resuming.
            launcher = "import runpy,sys;sys.path.insert(0,sys.argv.pop(1));runpy.run_module('tools.strength_v4',run_name='__main__')"
            os.execv(
                sys.executable,
                [sys.executable, "-P", "-c", launcher, str(source_root), *sys.argv[1:]],
            )
    require(
        sha(__file__) == inputs["files"]["tools/strength_v4.py"],
        "v4 owner is not its original archived code",
    )
    engine = args.engine.resolve()
    network = root / "results/precision-v4-2026-10-25/selected-v4.cai"
    if existing is not None:
        engine = existing.parent / "bin/caissa"
        network = existing.parent / "inputs/selected.cai"
        args.protocol = existing.parent / "inputs/PROTOCOL.json"
    rule = frozen_profile(args.protocol, args.expected_protocol_sha256, root)
    derivation = lineage(root, model, engine, network, rule, commit)
    stockfish = (
        existing.parent / "bin/stockfish"
        if existing is not None
        else args.stockfish.resolve()
    )
    require(
        stockfish.is_file() and sha(stockfish) == rule["matches"]["stockfish_sha256"],
        "v4 comparator bytes differ from pinned Stockfish19",
    )
    return rule, inputs, source_root, derivation, engine, network, stockfish


def completed(output, bindings):
    path = output / "STRENGTH_CAMPAIGN.json"
    if not path.exists():
        return None
    receipt = document(path)
    require(
        all(receipt.get(key) == value for key, value in bindings.items()),
        "closed v4 domain identity differs",
    )
    require(receipt.get("scope_closed") is True, "v4 completion is not closed")
    usage = document(output / "ACTIVE_USAGE.json")
    scope = document(output / "SCOPE.json")
    require(
        usage.get("closed") is True
        and scope.get("bindings") == bindings
        and receipt.get("origin_unix") == scope["origin_unix"]
        and receipt.get("deadline_unix") == scope["deadline_unix"]
        and scope["origin_unix"]
        <= receipt.get("completed_unix", 0)
        <= scope["deadline_unix"],
        "closed v4 budget or completion provenance differs",
    )
    proof = receipt.get("independent_artifact", {})
    path = output / proof.get("path", "")
    require(
        path.resolve().is_relative_to(output.resolve())
        and path.is_file()
        and sha(path) == proof.get("sha256"),
        "closed v4 independent proof changed or missing",
    )
    for ref in receipt.get("statistics_artifacts", []):
        path = output / ref["path"]
        require(
            path.resolve().is_relative_to(output.resolve())
            and sha(path) == ref["sha256"],
            "closed v4 statistics changed",
        )
    require(
        len(receipt.get("statistics_artifacts", []))
        == (1 if bindings["kind"] == "neural" else 3),
        "closed v4 sample inventory differs",
    )
    return receipt


def execute_domain(
    root, args, kind, rule, inputs, source_root, derivation, engine, network, stockfish
):
    output = root / SCOPES[kind]
    bindings = {
        "source_commit": inputs["commit"],
        "protocol_sha256": args.expected_protocol_sha256,
        "engine_sha256": ENGINE,
        "network_sha256": NETWORK,
        "kind": kind,
        "original_model_campaign_sha256": rule["strength_actor"][
            "original_model_campaign_sha256"
        ],
        "workflow_sha256": inputs["files"]["tools/strength_v4.py"],
        "parent_project_deadline_unix": PARENT_DEADLINE,
    }
    prior = completed(output, bindings)
    if prior is not None:
        return prior
    resume = (output / "SCOPE.json").exists()
    require(not resume or args.resume, "v4 existing scope requires explicit resume")
    resources = rule["strength_resources"]
    ceiling = resources["maximum_wall_seconds_per_domain"]
    require(
        resume or time.time() + ceiling <= PARENT_DEADLINE,
        "v4 domain would exceed the original parent deadline",
    )
    scope = RecoveryScope(
        output,
        bindings,
        ceiling,
        root / "runs/searched-full-model-v3",
        resources["minimum_free_gib"],
        resources["maximum_additional_gib_per_domain"],
        resume=resume,
        maximum_authorized_seconds=43200,
        maximum_active_seconds=resources["maximum_active_seconds_per_domain"],
    )
    power = None
    campaign = None
    scope_closed = False
    try:
        if not resume:
            atomic(output / "SOURCE_INPUTS.json", inputs)
        if not resume:
            (output / "inputs").mkdir()
            (output / "bin").mkdir()
            shutil.copyfile(engine, output / "bin/caissa")
            (output / "bin/caissa").chmod(0o755)
            shutil.copyfile(network, output / "inputs/selected.cai")
            shutil.copyfile(stockfish, output / "bin/stockfish")
            (output / "bin/stockfish").chmod(0o755)
            for name, item in derivation["paths"].items():
                shutil.copyfile(
                    item["path"], output / "inputs" / (name + Path(item["path"]).suffix)
                )
            shutil.copyfile(args.protocol, output / "inputs/PROTOCOL.json")
            shutil.copyfile(
                root / "config/strength-openings.json", output / "inputs/OPENINGS.json"
            )
            atomic(output / "DEPLOYMENT_LINEAGE.json", derivation)
        engine, network, stockfish = (
            output / "bin/caissa",
            output / "inputs/selected.cai",
            output / "bin/stockfish",
        )
        require(
            sha(engine) == ENGINE
            and sha(network) == NETWORK
            and sha(stockfish) == rule["matches"]["stockfish_sha256"],
            "v4 saved actor bytes changed",
        )
        require(
            sha(output / "inputs/PROTOCOL.json") == args.expected_protocol_sha256,
            "v4 saved profile changed",
        )
        source = output / "source"
        # Git remains the immutable source of an initial archive; later phases
        # copy the already frozen tree without consulting changed work files.
        if not source.exists():
            if source_root == root:
                archive_source(root, source, inputs["commit"], inputs["files"])
            else:
                source.mkdir()
                for name in inputs["files"]:
                    target = source / name
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(source_root / name, target)
        for name, digest in inputs["files"].items():
            require(sha(source / name) == digest, "v4 archived source changed: " + name)
        power = PowerGuard(resources["host_policy"])
        power.start(output)
        attempts = sorted((output / "attempts").glob("attempt-*"))
        require(
            len(attempts) < resources["maximum_attempts"],
            "v4 original attempt ceiling exhausted",
        )
        host = HostGuard(output, scope, power)
        atomic(
            output / ("HOST_START_" + str(len(attempts) + 1) + ".json"),
            {
                "unix": time.time(),
                "platform": platform.platform(),
                "cpu_count": os.cpu_count(),
                "processes": process_rows(),
            },
        )
        host.check()
        campaign = Campaign(
            output / "attempts" / f"attempt-{len(attempts)+1:03d}",
            bindings,
            scope.remaining(),
            absolute_deadline=min(scope.deadline, PARENT_DEADLINE),
            resource_guard=host.check,
        )

        def run(name, module, arguments):
            host.check()
            return campaign.run(
                name,
                [sys.executable, "-m", module, *map(str, arguments)],
                scope.remaining(),
                cwd=source,
            )

        schedule = (
            [("neural", None)]
            if kind == "neural"
            else [("external-" + str(i), (i, stockfish)) for i in range(3)]
        )
        roots = []
        for name, setting in schedule:
            directory = output / name
            roots.append(directory)
            config = output / "inputs" / (name + ".json")
            actual = configuration(
                rule, engine, network, output / "inputs/OPENINGS.json", setting
            )
            if config.exists():
                require(
                    document(config) == actual,
                    "v4 actor configuration changed on resume",
                )
            else:
                atomic(config, actual)
            run(
                "play-" + name,
                "arena.run",
                [config, directory, "--workers", rule["matches"]["workers"]],
            )
            run("statistics-" + name, "arena.statistics", [directory])
        failed = []
        if kind == "neural":
            try:
                run(
                    "independent-neural",
                    "verification.strength",
                    [
                        roots[0],
                        "--openings",
                        output / "inputs/OPENINGS.json",
                        "--engine-sha256",
                        ENGINE,
                        "--network-sha256",
                        NETWORK,
                        "--protocol",
                        output / "inputs/PROTOCOL.json",
                        "--neural",
                        "--require-full",
                    ],
                )
            except StageFailure as error:
                observed = document(campaign.output / "independent-neural.log")
                if (
                    error.record["exit"] != 1
                    or observed.get("reason")
                    != "full neural contribution failed its predeclared Elo endpoint"
                    or observed.get("observed", {}).get("games") != 4000
                ):
                    raise
                failed.append("G08 neural contribution failed its frozen endpoint")
        else:
            run(
                "independent-external",
                "verification.external_strength",
                [
                    *roots,
                    "--openings",
                    output / "inputs/OPENINGS.json",
                    "--engine-sha256",
                    ENGINE,
                    "--network-sha256",
                    NETWORK,
                    "--protocol",
                    output / "inputs/PROTOCOL.json",
                ],
            )
        proof = campaign.output / (
            "independent-neural.log" if kind == "neural" else "independent-external.log"
        )
        result = {
            **bindings,
            "status": (
                "completed fixed full strength sample"
                if not failed
                else "completed fixed full sample with failed gate"
            ),
            "failed_domains": failed,
            "origin_unix": scope.state["origin_unix"],
            "deadline_unix": scope.deadline,
            "completed_unix": time.time(),
            "campaigns": [str(p.relative_to(output)) for p in roots],
            "scope_closed": True,
            "independent_artifact": {
                "path": str(proof.relative_to(output)),
                "sha256": sha(proof),
            },
            "statistics_artifacts": [
                {
                    "path": str((p / "SUMMARY.json").relative_to(output)),
                    "sha256": sha(p / "SUMMARY.json"),
                }
                for p in roots
            ],
            "absolute_elo": None,
            "full_acceptance": False,
        }
        campaign.close(result["status"], result)
        scope.close()
        scope_closed = True
        atomic(output / "STRENGTH_CAMPAIGN.json", result)
        return result
    except BaseException as error:
        if campaign is not None:
            campaign.close(
                "failed", {"type": type(error).__name__, "reason": str(error)}
            )
        atomic(
            output / "FAILED.json",
            {
                "reason": str(error),
                "type": type(error).__name__,
                "original_deadline_unix": scope.deadline,
                "observed_unix": time.time(),
                "full_acceptance": False,
            },
        )
        raise
    finally:
        try:
            if power is not None:
                power.close()
        finally:
            if not scope_closed:
                scope.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("kind", choices=["neural", "external", "sequence"])
    parser.add_argument("--protocol", type=Path, required=True)
    parser.add_argument("--expected-protocol-sha256", required=True)
    parser.add_argument(
        "--engine", type=Path, default=Path("build-search-semantics/caissa")
    )
    parser.add_argument(
        "--stockfish",
        type=Path,
        default=Path("runs/project-continuation-v1/bin/stockfish"),
    )
    parser.add_argument("--resume", action="store_true")
    parser.add_argument(
        "--check-only",
        action="store_true",
        help="Read immutable inputs without creating a strength scope or starting games",
    )
    args = parser.parse_args()
    root = Path.cwd().resolve()
    lock = None
    try:
        lock = (root / "runs/TIMED_STRENGTH.lock").open("a")
        try:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise ValueError(
                "another decisive strength owner holds the host"
            ) from error
        rule, inputs, source_root, derivation, engine, network, stockfish = context(
            root, args
        )
        if args.check_only:
            print(
                json.dumps(
                    {
                        "status": "ready",
                        "source_commit": inputs["commit"],
                        "profile_sha256": args.expected_protocol_sha256,
                        "engine_sha256": ENGINE,
                        "network_sha256": NETWORK,
                        "lineage": derivation,
                        "strength_scopes_created": False,
                        "games_started": False,
                        "full_acceptance": False,
                    }
                )
            )
            return 0
        results = []
        for kind in (
            ["neural", "external"] if args.kind == "sequence" else [args.kind]
        ):
            results.append(
                execute_domain(
                    root,
                    args,
                    kind,
                    rule,
                    inputs,
                    source_root,
                    derivation,
                    engine,
                    network,
                    stockfish,
                )
            )
            # The next phase keeps the first phase's archived owner and inputs.
            first = root / SCOPES[kind]
            source_root = first / "source"
            engine = first / "bin/caissa"
            network = first / "inputs/selected.cai"
            stockfish = first / "bin/stockfish"
        print(
            json.dumps(
                {
                    "status": "completed v4 requested sequence",
                    "domains": results,
                    "full_acceptance": False,
                }
            )
        )
        return 2 if any(row["failed_domains"] for row in results) else 0
    except (
        ValueError,
        KeyError,
        OSError,
        RuntimeError,
        subprocess.SubprocessError,
    ) as error:
        print(
            json.dumps(
                {"status": "failed", "reason": str(error), "full_acceptance": False}
            )
        )
        return 1
    finally:
        if lock is not None:
            lock.close()


if __name__ == "__main__":
    raise SystemExit(main())
