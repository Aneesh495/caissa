"""Own fixed parallel/heuristic matches without changing any learned actor.

Each domain uses its original output, source archive and cumulative limits.
This owner never starts automatically alongside another decisive campaign.
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

from tools.campaign_process import Campaign, StageFailure, atomic
from tools.finalize_corpus import archive_source
from tools.full_strength import HostGuard
from tools.host_lease import HostLease
from tools.power_guard import POLICY, PowerGuard
from tools.recovery_scope import RecoveryScope
from tools.strength_v4_profile import lineage
from verification.g07_audit import strength_settled
from verification.source import (
    PRODUCT,
    require,
    snapshot,
    verify_archive,
    verify_checkout,
)
from verification.systems_strength import contract, read


def sha(path):
    import hashlib

    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def configuration(rule, row, engine, network, openings):
    # This producer constructs its actors separately from the independent
    # reader's option inventory. Both are constrained by the frozen profile.
    common = {
        "Hash": 16,
        "Evaluation Cache": True,
        "Tactical Generation": True,
        "Lazy Neural": True,
        "Neural Bounds": False,
        "Ordering Hints": False,
        "Null Move": True,
        "LMR": True,
        "Extensions": True,
        "Futility": True,
        "SEE": True,
        "History": True,
        "PVS": True,
        "Aspiration": True,
        "Quiescence": True,
        "Use Table": True,
    }
    actors = {}
    for role in ["candidate", "opponent"]:
        parallel = rule["kind"] == "parallel"
        options = {
            **common,
            "Threads": row["threads"] if role == "candidate" else 1,
            "Use Neural": parallel,
        }
        if parallel:
            options.update({"EvalFile": str(network), "Neural Weight": 10})
        elif role == "opponent":
            options[row["switch"]] = False
        actors[role] = {
            "name": "Caissa " + rule["kind"] + " " + row["id"] + " " + role,
            "command": [str(engine)],
            "options": options,
        }
    return {
        "profile": "full original " + rule["kind"] + " comparison",
        **actors,
        "openings": str(openings),
        "pairs": row["pairs"],
        row["budget_kind"]: row["budget"],
        "max_plies": 512,
        "warmup_nodes": 1,
        "transport_allowance_ms": 150,
    }


def context(root, args):
    require(
        strength_settled(root),
        "original frozen strength pipeline has not settled; defer systems matches",
    )
    rule, base, pin = contract(args.profile, root / "config/protocol-v4.json")
    require(
        pin == args.expected_profile_sha256, "systems external profile identity differs"
    )
    require(rule["kind"] == args.kind, "systems owner domain differs from its profile")
    output = root / rule["resources"]["output"]
    require(
        not (output / "SYSTEMS_STRENGTH.json").exists(),
        "systems comparison domain is already closed; do not rerun completed samples",
    )
    source_record = output / "SOURCE_INPUTS.json"
    if source_record.exists():
        require(args.resume, "existing systems source requires explicit resume")
        _, source = read(source_record)
        require(
            source["commit"] == args.expected_commit,
            "systems original source commit differs",
        )
        verify_archive(output / "source", root, source, args.expected_commit, PRODUCT)
        if Path(__file__).resolve() != output / "source/tools/systems_strength.py":
            launcher = "import runpy,sys;sys.path.insert(0,sys.argv.pop(1));runpy.run_module('tools.systems_strength',run_name='__main__')"
            os.execv(
                sys.executable,
                [
                    sys.executable,
                    "-P",
                    "-c",
                    launcher,
                    str(output / "source"),
                    *sys.argv[1:],
                ],
            )
        saved = output / "inputs/PROFILE.json"
        require(sha(saved) == pin, "systems saved prospective profile changed")
        rule, base, _ = contract(saved, output / "inputs/BASE_PROTOCOL.json")
        return rule, base, source, output, None
    require(
        not output.exists() and not args.resume,
        "systems output exists without its original source; no reset",
    )
    require(
        args.profile.resolve()
        == root / "config" / ("systems-" + args.kind + "-v1.json"),
        "systems prospective profile must be committed at its fixed config path",
    )
    require(
        Path(__file__).resolve() == root / "tools/systems_strength.py",
        "initial systems owner must execute its trusted checkout source",
    )
    source = {
        "schema": "caissa-source-inputs-v2",
        "policy": PRODUCT,
        "commit": args.expected_commit,
        "files": snapshot(root, args.expected_commit, PRODUCT),
    }
    verify_checkout(root, source, args.expected_commit, PRODUCT)
    require(
        not subprocess.check_output(
            ["git", "status", "--porcelain"], cwd=root, text=True, timeout=10
        ),
        "commit all prospective systems source and inputs before starting games",
    )
    frozen = root / "runs/full-neural-strength-v4"
    derivation = lineage(
        root,
        root / "runs/searched-full-model-v3",
        frozen / "bin/caissa",
        frozen / "inputs/selected.cai",
        base,
        args.expected_commit,
    )
    return rule, base, source, output, derivation


def execute(root, args):
    rule, base, source, output, derivation = context(root, args)
    if args.check_only:
        return {
            "status": "ready",
            "kind": args.kind,
            "source_commit": source["commit"],
            "profile_sha256": args.expected_profile_sha256,
            "games_started": False,
            "scope_created": False,
            "full_acceptance": False,
        }
    resources = rule["resources"]
    resume = (output / "SCOPE.json").exists()
    require(
        resume
        or time.time() + resources["maximum_wall_seconds"]
        <= resources["parent_deadline_unix"],
        "systems domain cannot fit within the original parent deadline",
    )
    lease = HostLease(root / "runs")
    scope = power = campaign = None
    try:
        bindings = {
            "source_commit": source["commit"],
            "kind": args.kind,
            "profile_sha256": args.expected_profile_sha256,
            "engine_sha256": base["strength_actor"]["engine_sha256"],
            "network_sha256": base["strength_actor"]["network_sha256"],
            "original_model_campaign_sha256": base["strength_actor"][
                "original_model_campaign_sha256"
            ],
            "parent_deadline_unix": resources["parent_deadline_unix"],
        }
        scope = RecoveryScope(
            output,
            bindings,
            resources["maximum_wall_seconds"],
            output / "empty-input-accounting",
            10,
            20,
            resume=resume,
            maximum_authorized_seconds=43200,
            maximum_active_seconds=resources["maximum_active_seconds"],
        )
        attempts = sorted((output / "attempts").glob("attempt-*"))
        require(
            len(attempts) < resources["maximum_attempts"],
            "systems original attempt ceiling exhausted",
        )
        power = PowerGuard(POLICY if sys.platform == "darwin" else None)
        power.start(output)
        host = HostGuard(output, scope, power)

        def guard():
            lease.check()
            host.check()

        guard()
        campaign = Campaign(
            output / "attempts" / f"attempt-{len(attempts)+1:03d}",
            bindings,
            scope.remaining(),
            absolute_deadline=scope.deadline,
            resource_guard=guard,
        )
        if not resume:
            atomic(output / "SOURCE_INPUTS.json", source)
            archive_source(root, output / "source", source["commit"], source["files"])
            (output / "inputs").mkdir()
            (output / "bin").mkdir()
            frozen = root / "runs/full-neural-strength-v4"
            for origin, destination in [
                (frozen / "bin/caissa", output / "bin/caissa"),
                (frozen / "inputs/selected.cai", output / "inputs/selected.cai"),
                (args.profile, output / "inputs/PROFILE.json"),
                (
                    root / "config/protocol-v4.json",
                    output / "inputs/BASE_PROTOCOL.json",
                ),
                (
                    root / "config/strength-openings.json",
                    output / "inputs/OPENINGS.json",
                ),
            ]:
                scope.check()
                shutil.copyfile(origin, destination)
                require(
                    sha(origin) == sha(destination), "systems frozen input copy differs"
                )
            (output / "bin/caissa").chmod(0o755)
            atomic(output / "DEPLOYMENT_LINEAGE.json", derivation)
        engine, network, openings = (
            output / "bin/caissa",
            output / "inputs/selected.cai",
            output / "inputs/OPENINGS.json",
        )
        saved_rule, saved_base, saved_pin = contract(
            output / "inputs/PROFILE.json", output / "inputs/BASE_PROTOCOL.json"
        )
        from verification.draw_history import typed_equal

        require(
            saved_pin == args.expected_profile_sha256
            and typed_equal(saved_rule, rule)
            and typed_equal(saved_base, base),
            "systems saved profile or original actor contract changed",
        )
        for path, expected in [
            (engine, bindings["engine_sha256"]),
            (network, bindings["network_sha256"]),
            (openings, base["strength_actor"]["openings_sha256"]),
        ]:
            require(
                sha(path) == expected, "systems saved actor/opening identity changed"
            )

        def run(name, module, arguments):
            return campaign.run(
                name,
                [sys.executable, "-m", module, *map(str, arguments)],
                scope.remaining(),
                cwd=output / "source",
                env=lease.environment(),
                pass_fds=(lease.stream.fileno(),),
            )

        outcomes = []
        for row in rule["comparisons"]:
            guard()
            config = configuration(rule, row, engine, network, openings)
            path = output / "inputs" / (row["id"] + ".json")
            if path.exists():
                from verification.draw_history import typed_equal

                require(
                    typed_equal(read(path)[1], config),
                    "systems resumed actor configuration changed",
                )
            else:
                atomic(path, config)
            destination = output / "matches" / row["id"]
            run(
                "play-" + row["id"],
                "arena.run",
                [path, destination, "--workers", resources["workers"]],
            )
            run("statistics-" + row["id"], "arena.statistics", [destination])
            try:
                run(
                    "independent-" + row["id"],
                    "verification.systems_strength",
                    [
                        destination,
                        "--profile",
                        output / "inputs/PROFILE.json",
                        "--expected-profile-sha256",
                        args.expected_profile_sha256,
                        "--base-protocol",
                        output / "inputs/BASE_PROTOCOL.json",
                        "--comparison",
                        row["id"],
                        "--openings",
                        openings,
                        "--maximum-seconds",
                        min(3600, max(1, int(scope.remaining()))),
                    ],
                )
            except StageFailure as error:
                report = read(campaign.output / ("independent-" + row["id"] + ".log"))[
                    1
                ]
                if not (
                    error.record["exit"] == 1
                    and report.get("reason")
                    == "declared strength sample contains unfinished games"
                ):
                    raise
                # Finish other prospectively frozen comparisons while retaining
                # this failed fixed sample. Never replace its unfinished games.
            report_path = campaign.output / ("independent-" + row["id"] + ".log")
            report = read(report_path)[1]
            outcomes.append(
                {
                    "comparison": row["id"],
                    "status": report["status"],
                    "raw_replay": str(report_path.relative_to(output)),
                    "sha256": sha(report_path),
                    "summary_sha256": sha(destination / "SUMMARY.json"),
                }
            )
        result = {
            **bindings,
            "status": "completed all scheduled comparison attempts",
            "outcomes": outcomes,
            "failed_comparisons": [
                x["comparison"] for x in outcomes if x["status"] != "passed"
            ],
            "completed_unix": time.time(),
            "scope_closed": True,
            "full_G10_certified": False,
            "neural_contribution_certified": False,
            "absolute_elo": None,
            "full_acceptance": False,
        }
        campaign.close(result["status"], result)
        scope.close()
        scope = None
        atomic(output / "SYSTEMS_STRENGTH.json", result)
        return result
    except BaseException as error:
        if campaign is not None:
            campaign.close(
                "failed", {"type": type(error).__name__, "reason": str(error)}
            )
        if scope is not None:
            atomic(
                output / f"FAILED-{time.time_ns()}.json",
                {
                    "reason": str(error),
                    "observed_unix": time.time(),
                    "full_acceptance": False,
                },
            )
        raise
    finally:
        if power is not None:
            power.close()
        if scope is not None:
            scope.close()
        lease.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("kind", choices=["parallel", "heuristics"])
    parser.add_argument("--profile", type=Path, required=True)
    parser.add_argument("--expected-profile-sha256", required=True)
    parser.add_argument("--expected-commit", required=True)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--check-only", action="store_true")
    args = parser.parse_args()
    try:
        print(json.dumps(execute(Path.cwd().resolve(), args)))
    except (
        ValueError,
        KeyError,
        OSError,
        TypeError,
        TimeoutError,
        StageFailure,
    ) as error:
        print(
            json.dumps(
                {"status": "rejected", "reason": str(error), "full_acceptance": False}
            )
        )
        raise SystemExit(1)


if __name__ == "__main__":
    main()
