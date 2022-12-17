"""Original deferred-state correctness and randomized runtime diagnostic.

This profile never trains, selects a model or plays a strength game. Its native
work is restricted to bounded hosted runners while the local arena owns timing.
"""

import argparse
import contextlib
import hashlib
import json
import os
import platform
import random
import shutil
import statistics
import subprocess
import sys
import time
from pathlib import Path

from arena.client import UciClient
from tools.campaign_process import Campaign, atomic
from tools.performance import info, replay
from tools.heuristic_study import avoid_decisive_matches

PROFILE_SHA256 = "91add4ccf9a33f46358ca5381f2dbf1679eae02697a0c891b452e8749ad4821a"
NETWORK = Path("results/precision-v4-2026-10-25/selected-v4.cai")


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def profile(path):
    if sha(path) != PROFILE_SHA256:
        raise ValueError("deferred-state profile differs from its prospective pin")
    return json.loads(path.read_text())


def fingerprint(move, observed):
    timing = {"elapsed_ms", "eval_ns"}
    return {
        "move": move,
        "info": {
            k: v for k, v in observed.items() if k not in {"time", "nps", "stats"}
        },
        "stats": {
            k: v
            for k, v in observed["stats"].items()
            if k not in timing and not k.startswith("accumulator_")
        },
    }


def measure(args, rule):
    args.output.mkdir(parents=True, exist_ok=False)
    deadline = min(
        time.time() + rule["measurement"]["maximum_seconds"],
        rule["resources"]["deadline_unix"],
    )
    active_deadline = time.monotonic() + rule["measurement"]["maximum_seconds"]
    reference = rule["references"][platform.system()]
    if (
        sha(args.previous) != reference["sha256"]
        or sha(NETWORK) != rule["network_sha256"]
    ):
        raise ValueError("runtime diagnostic actor or network identity changed")
    config = rule["measurement"]
    atomic(
        args.output / "CONFIG.json",
        {
            "profile_sha256": PROFILE_SHA256,
            "engine_sha256": sha(args.engine),
            "reference_sha256": sha(args.previous),
            "network_sha256": sha(NETWORK),
            "platform": platform.platform(),
            "cpu_count": os.cpu_count(),
            "deadline_unix": deadline,
            "full_acceptance": False,
        },
    )
    rng = random.Random(config["order_seed"])
    sessions, rows, comparisons = [], [], 0
    try:
        with (args.output / "observations.jsonl").open("x") as raw:
            for weight in config["weights"]:
                for cached in config["evaluation_cache"]:
                    with contextlib.ExitStack() as cleanup:
                        clients = {}
                        for arm in config["arms"]:
                            if (
                                time.time() >= deadline
                                or time.monotonic() >= active_deadline
                            ):
                                raise TimeoutError(
                                    "deferred runtime cumulative deadline exhausted"
                                )
                            options = {
                                "Hash": config["hash_mib"],
                                "Threads": 1,
                                "Search Stats": True,
                                "Evaluation Cache": cached,
                                "Tactical Generation": config["tactical_generation"],
                                "Neural Bounds": False,
                                "Ordering Hints": False,
                                "EvalFile": str(NETWORK.resolve()),
                                "Use Neural": True,
                                "Neural Weight": weight,
                                "Scalar Neural": False,
                            }
                            executable = (
                                args.previous
                                if arm == "archived-eager"
                                else args.engine
                            )
                            if arm != "archived-eager":
                                options["Lazy Neural"] = arm == "stack-lazy"
                            client = cleanup.enter_context(
                                UciClient(
                                    [str(executable.resolve())], options, warmup_nodes=1
                                )
                            )
                            clients[arm] = client
                            sessions.append(
                                {
                                    "arm": arm,
                                    "weight": weight,
                                    "cached": cached,
                                    "pid": client.process.pid,
                                    "handshake": client.handshake,
                                    "commands": client.configuration_commands,
                                }
                            )
                            atomic(args.output / "SESSIONS.json", sessions)
                        for repeat in range(config["repeats"]):
                            for position in config["positions"]:
                                order = rng.sample(config["arms"], len(config["arms"]))
                                expected = None
                                for arm in order:
                                    if (
                                        time.time() >= deadline
                                        or time.monotonic() >= active_deadline
                                    ):
                                        raise TimeoutError(
                                            "deferred runtime cumulative deadline exhausted"
                                        )
                                    client = clients[arm]
                                    client.send("ucinewgame")
                                    client.send("isready")
                                    client.until("readyok", 5)
                                    move, elapsed, lines = client.play(
                                        position["fen"], [], nodes=config["nodes"]
                                    )
                                    observed = info(lines)
                                    row = {
                                        "arm": arm,
                                        "weight": weight,
                                        "cached": cached,
                                        "repeat": repeat,
                                        "position": position,
                                        "order": order,
                                        "move": move,
                                        "roundtrip_ms": elapsed,
                                        "request": client.last_request,
                                        "lines": lines,
                                        "observed": observed,
                                    }
                                    raw.write(
                                        json.dumps(
                                            row, separators=(",", ":"), allow_nan=False
                                        )
                                        + "\n"
                                    )
                                    raw.flush()
                                    if raw.tell() > 32 * 1024 * 1024:
                                        raise ValueError(
                                            "deferred runtime observation byte ceiling"
                                        )
                                    replay(position["fen"], move, observed["pv"])
                                    current = fingerprint(move, observed)
                                    if expected is not None and current != expected:
                                        raise ValueError(
                                            "archived/eager/deferred exact search fingerprint differs"
                                        )
                                    expected = current
                                    if (
                                        not 0
                                        < observed["stats"]["visited_nodes"]
                                        <= config["nodes"]
                                    ):
                                        raise ValueError(
                                            "runtime search violated its fixed node ceiling"
                                        )
                                    rows.append(row)
                                comparisons += 1
                                atomic(
                                    args.output / "PROGRESS.json",
                                    {
                                        "completed_queries": len(rows),
                                        "exact_triplets": comparisons,
                                        "expected_queries": len(config["weights"])
                                        * len(config["evaluation_cache"])
                                        * config["repeats"]
                                        * len(config["positions"])
                                        * len(config["arms"]),
                                        "unix": time.time(),
                                    },
                                )
        results = []
        for weight in config["weights"]:
            for cached in config["evaluation_cache"]:
                selected = [
                    r for r in rows if r["weight"] == weight and r["cached"] == cached
                ]
                by_arm = {
                    arm: [r for r in selected if r["arm"] == arm]
                    for arm in config["arms"]
                }
                ratios = {}
                for baseline in ["archived-eager", "stack-eager"]:
                    ratios[baseline] = [
                        a["roundtrip_ms"] / b["roundtrip_ms"]
                        for a, b in zip(
                            by_arm["stack-lazy"], by_arm[baseline], strict=True
                        )
                    ]
                results.append(
                    {
                        "weight": weight,
                        "cached": cached,
                        "median_lazy_to_archived_wall_ratio": statistics.median(
                            ratios["archived-eager"]
                        ),
                        "median_lazy_to_stack_eager_wall_ratio": statistics.median(
                            ratios["stack-eager"]
                        ),
                        "paired_ratios": ratios,
                        "work": {
                            arm: {
                                key: sum(
                                    r["observed"]["stats"].get(key, 0)
                                    for r in by_arm[arm]
                                )
                                for key in [
                                    "accumulator_pushes",
                                    "accumulator_materializations",
                                    "accumulator_copies",
                                    "accumulator_refreshes",
                                    "accumulator_delta_squares",
                                ]
                            }
                            for arm in ["stack-eager", "stack-lazy"]
                        },
                    }
                )
        summary = {
            "status": "passed",
            "queries": len(rows),
            "exact_triplets": comparisons,
            "results": results,
            "claim": "Host-specific randomized wall-time diagnostic. Ratios below one favor deferral. No Elo or playing-strength estimate.",
            "full_acceptance": False,
        }
        atomic(args.output / "SUMMARY.json", summary)
    except BaseException as error:
        atomic(
            args.output / "FAILED.json",
            {
                "status": "failed",
                "error": repr(error),
                "completed_queries": len(rows),
                "exact_triplets": comparisons,
            },
        )
        raise


def campaign(args, rule):
    resources = rule["resources"]
    if os.environ.get("GITHUB_ACTIONS") != "true":
        raise ValueError("this native diagnostic requires an isolated hosted runner")
    run_number, attempt = int(os.environ["GITHUB_RUN_NUMBER"]), int(
        os.environ["GITHUB_RUN_ATTEMPT"]
    )
    if not 1 <= run_number <= resources["maximum_jobs_per_platform"] or attempt != 1:
        raise ValueError("deferred hosted cumulative execution ceiling exhausted")
    if time.time() >= resources["deadline_unix"]:
        raise TimeoutError("deferred original wall deadline exhausted")
    commit = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], text=True, timeout=5
    ).strip()
    if commit != args.expected_commit or subprocess.check_output(
        ["git", "status", "--porcelain"], text=True, timeout=5
    ):
        raise ValueError("deferred native source must match the clean external commit")
    if sha(NETWORK) != rule["network_sha256"]:
        raise ValueError("deferred fixed network changed")
    maximum = min(
        resources["maximum_job_seconds"], resources["deadline_unix"] - time.time()
    )
    owner = Campaign(
        args.output,
        {
            "source_commit": commit,
            "profile_sha256": PROFILE_SHA256,
            "run_number": run_number,
            "run_attempt": attempt,
            "network_sha256": sha(NETWORK),
            "original_origin_unix": resources["origin_unix"],
            "original_deadline_unix": resources["deadline_unix"],
            "full_acceptance": False,
        },
        maximum,
        absolute_deadline=resources["deadline_unix"],
    )
    programs = {}
    try:
        # Pin a local copy of the already published reference. Never overwrite
        # its tracked bytes or rebuild it under the new source identity.
        reference = rule["references"][platform.system()]
        previous = args.output / "archived-caissa"
        shutil.copyfile(reference["path"], previous)
        previous.chmod(0o755)
        if sha(previous) != reference["sha256"]:
            raise ValueError("deferred archived reference changed")
        for mode in rule["correctness"]["modes"]:
            build = args.output / ("build-" + mode)
            flags = (
                []
                if mode == "release"
                else [
                    (
                        "-DCAISSA_SANITIZE=ON"
                        if mode == "address-undefined"
                        else "-DCAISSA_TSAN=ON"
                    )
                ]
            )
            owner.run(
                mode + "-configure",
                [
                    "cmake",
                    "-S",
                    ".",
                    "-B",
                    str(build),
                    "-DCMAKE_BUILD_TYPE=Release",
                    *flags,
                ],
                30,
            )
            owner.run(
                mode + "-build",
                ["cmake", "--build", str(build), "-j", "2"],
                resources["maximum_build_seconds"],
            )
            owner.run(
                mode + "-ctest",
                ["ctest", "--test-dir", str(build), "--output-on-failure"],
                resources["maximum_correctness_seconds_per_mode"],
            )
            report = (build / "CTestTestfile.cmake").read_text().count("add_test(")
            if report != rule["correctness"]["native_cases"]:
                raise ValueError(
                    "deferred native test inventory differs from frozen profile"
                )
            owner.run(
                mode + "-million",
                [
                    str(build / "accumulator_stack_test"),
                    str(NETWORK),
                    str(rule["correctness"]["transitions_per_mode"]),
                ],
                resources["maximum_correctness_seconds_per_mode"],
            )
            programs[mode] = {
                name: sha(build / name) for name in ["caissa", "accumulator_stack_test"]
            }
            atomic(
                args.output / "PROGRAMS.json",
                {"source_commit": commit, "programs": programs},
            )
            if mode == "release":
                owner.run(
                    "runtime",
                    [
                        sys.executable,
                        "-m",
                        "tools.deferred_neural",
                        "--measure",
                        "--profile",
                        str(args.profile),
                        "--engine",
                        str(build / "caissa"),
                        "--previous",
                        str(previous),
                        "--output",
                        str(args.output / "runtime"),
                    ],
                    rule["measurement"]["maximum_seconds"],
                )
        total = sum(
            path.stat().st_size for path in args.output.rglob("*") if path.is_file()
        )
        if total > resources["maximum_artifact_bytes_per_host"]:
            raise ValueError("deferred raw artifact byte ceiling exhausted")
        owner.close(
            "passed",
            {"programs": programs, "raw_bytes": total, "full_acceptance": False},
        )
    except BaseException as error:
        owner.close("failed", {"error": repr(error)})
        raise


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--profile", type=Path, default=Path("config/deferred-neural-v1.json")
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--expected-commit")
    parser.add_argument("--measure", action="store_true")
    parser.add_argument("--engine", type=Path)
    parser.add_argument("--previous", type=Path)
    args = parser.parse_args()
    rule = profile(args.profile)
    avoid_decisive_matches()
    if args.measure:
        if args.engine is None or args.previous is None:
            parser.error("measurement actors required")
        measure(args, rule)
    else:
        campaign(args, rule)


if __name__ == "__main__":
    main()
