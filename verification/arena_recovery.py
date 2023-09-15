"""Independently reconstruct a killed partial pair and its recovered journals.

A saved pass boolean cannot replace the authoritative pre-kill game bytes,
actual signal/exit record, torn-write fixtures or independently legal PGNs.
Training and original-data recovery remain separate G11 components.
"""

import argparse
import hashlib
import json
import math
import re
import shutil
import os
import sys
import time
from pathlib import Path

import chess

from verification.bundle import strict_json
from verification.draw_history import typed_equal
from verification.source import require

FILES = {
    "CONFIG.json",
    "ARENA_INPUT.json",
    "OPENINGS.json",
    "KILL.json",
    "FINISHED.json",
    "engine",
    "interrupted.log",
    "resumed.log",
    "statistics.log",
    "before/000000-0.json",
    "partial-before/000000-0.pgn.tmp",
    "partial-before/000000-1.json.tmp",
    "arena/RECOVERY_READY.json",
    "arena/CONFIG.json",
    "arena/PROTOCOL.json",
    "arena/SUMMARY.json",
    *{f"arena/pairs/{pair:06d}.json" for pair in range(2)},
    *{
        f"arena/games/{pair:06d}-{reverse}.{extension}"
        for pair in range(2)
        for reverse in range(2)
        for extension in ["json", "pgn"]
    },
}


def admit(config, expected_engine, expected_commit):
    require(
        config.get("schema") == "caissa-arena-recovery-observations-v1"
        and config.get("profile") == "recovery-component-only",
        "G11 arena requires raw forced-recovery observations",
    )
    require(
        config.get("engine_sha256") == expected_engine
        and config.get("source_commit") == expected_commit
        and re.fullmatch("[0-9a-f]{40}", expected_commit) is not None,
        "G11 arena source/program identity differs",
    )
    for key, value in {
        "maximum_seconds": 120,
        "maximum_output_bytes": 128 * 1024**2,
        "minimum_free_bytes": 10 * 1024**3,
    }.items():
        require(
            type(config.get(key)) is int and config[key] == value,
            "G11 arena original resource bounds differ",
        )
    start, deadline = config.get("started_unix"), config.get("deadline_unix")
    require(
        all(type(x) in {int, float} and math.isfinite(x) for x in [start, deadline])
        and deadline == start + 120,
        "G11 arena original deadline is invalid",
    )


def native_resume(
    root,
    destination,
    identity,
    expected_engine,
    guard,
    remaining,
    *,
    replay_engine=None,
):
    """Re-execute resumption in a new owned tree using only verified bytes."""
    from tools.campaign_process import Campaign, atomic
    from tools.host_lease import HostLease, inherited, ENVIRONMENT
    from verification.match_journals import verify as journals

    destination = Path(destination).resolve()
    require(
        not destination.is_relative_to(root.resolve())
        and not root.resolve().is_relative_to(destination),
        "G11 native replay must be separate from original evidence",
    )
    destination.mkdir(parents=True, exist_ok=False)
    lease = campaign = None
    previous_environment = os.environ.get(ENVIRONMENT)
    try:
        lock_root = Path("runs")
        lock_root.mkdir(exist_ok=True)
        inherited_lease = (
            inherited(lock_root / "TIMED_STRENGTH.lock")
            if os.environ.get(ENVIRONMENT) is not None
            else False
        )
        if not inherited_lease:
            lease = HostLease(lock_root)
            os.environ[ENVIRONMENT] = str(lease.stream.fileno())
        descriptor = (
            int(os.environ[ENVIRONMENT]) if inherited_lease else lease.stream.fileno()
        )
        environment = {**os.environ, ENVIRONMENT: str(descriptor)}
        binary = destination / "engine"
        shutil.copyfile(
            root / "engine" if replay_engine is None else replay_engine, binary
        )
        binary.chmod(0o755)
        require(
            hashlib.sha256(binary.read_bytes()).hexdigest() == expected_engine,
            "G11 replay executable differs",
        )
        shutil.copyfile(root / "OPENINGS.json", destination / "OPENINGS.json")
        config = json.loads(json.dumps(identity["config"]))
        for role in ["candidate", "opponent"]:
            config[role]["command"] = [str(binary)]
        config["openings"] = str(destination / "OPENINGS.json")
        atomic(destination / "INPUT.json", config)
        arena = destination / "arena"
        (arena / "games").mkdir(parents=True)
        (arena / "pairs").mkdir()
        protected = arena / "games/000000-0.json"
        shutil.copyfile(root / "before/000000-0.json", protected)
        for name in ["000000-0.pgn.tmp", "000000-1.json.tmp"]:
            shutil.copyfile(root / "partial-before" / name, arena / "games" / name)
        ceiling = max(0, min(60, remaining()))
        require(ceiling > 1, "G11 native replay original deadline exhausted")

        def native_guard():
            if lease is not None:
                lease.check()
            else:
                require(
                    inherited(lock_root / "TIMED_STRENGTH.lock"),
                    "G11 inherited host lease was lost",
                )
            guard()

        campaign = Campaign(
            destination / "execution",
            {
                "component": "G11 arena independent resumption",
                "engine_sha256": expected_engine,
            },
            ceiling,
            resource_guard=native_guard,
        )
        code = Path(__file__).resolve().parents[1]
        launcher = "import runpy,sys;sys.path.insert(0,sys.argv.pop(1));runpy.run_module('arena.run',run_name='__main__')"
        campaign.run(
            "native-resume",
            [
                sys.executable,
                "-P",
                "-c",
                launcher,
                str(code),
                str(destination / "INPUT.json"),
                str(arena),
                "--workers",
                "1",
            ],
            ceiling,
            env=environment,
            pass_fds=(descriptor,),
        )
        expected_protected = hashlib.sha256(
            (root / "before/000000-0.json").read_bytes()
        ).hexdigest()
        require(
            hashlib.sha256(protected.read_bytes()).hexdigest() == expected_protected,
            "G11 independent native resumption rewrote a committed game",
        )
        guard()
        replay = journals(
            arena, maximum_seconds=max(1, min(60, remaining())), tick=native_guard
        )
        for pair in range(2):
            original = strict_json((root / f"arena/pairs/{pair:06d}.json").read_bytes())
            actual = strict_json((arena / f"pairs/{pair:06d}.json").read_bytes())
            for left, right in zip(original["games"], actual["games"]):
                for key in [
                    "initial",
                    "moves",
                    "result",
                    "termination",
                    "culprit",
                    "candidate_color",
                    "pair",
                    "reverse",
                ]:
                    require(
                        typed_equal(left[key], right[key]),
                        "G11 native resumption changed the deterministic game: " + key,
                    )
        result = {
            "status": "passed",
            "actual_native_exit": 0,
            "protected_game_sha256": expected_protected,
            "game_journals": replay["game_journals"],
            "pgn_files": replay["pgn_files"],
            "new_games_executed": 3,
            "engine_sha256": expected_engine,
            "full_G11_certified": False,
        }
        atomic(destination / "NATIVE_RESUMPTION.json", result)
        campaign.close("completed independent native resumption", result)
        return result
    except BaseException as error:
        if campaign is not None:
            campaign.close("failed", {"reason": str(error)})
        raise
    finally:
        if lease is not None:
            if previous_environment is None:
                os.environ.pop(ENVIRONMENT, None)
            else:
                os.environ[ENVIRONMENT] = previous_environment
            lease.close()


def verify(
    root,
    expected_engine,
    expected_commit,
    maximum_seconds=60,
    tick=None,
    native_output=None,
):
    from tools.heuristic_study import avoid_decisive_matches
    from verification.match_journals import verify as journals
    from verification.strength import verify_campaign

    avoid_decisive_matches()
    require(
        type(maximum_seconds) in {int, float}
        and math.isfinite(maximum_seconds)
        and 0 < maximum_seconds <= 120,
        "finite arena recovery replay ceiling required",
    )
    root = Path(root)
    require(
        root.is_dir() and not root.is_symlink(),
        "G11 arena evidence must be a real directory",
    )
    started, wall = time.monotonic(), time.time()

    def guard():
        if tick is not None:
            tick()
        require(
            time.monotonic() - started < maximum_seconds
            and time.time() - wall < maximum_seconds,
            "G11 arena original replay ceiling exhausted",
        )

    actual = set()
    for path in root.rglob("*"):
        guard()
        require(not path.is_symlink(), "G11 arena linked raw evidence is forbidden")
        require(
            path.is_dir() or path.is_file(),
            "G11 arena nonregular evidence is forbidden",
        )
        if path.is_file():
            actual.add(str(path.relative_to(root)))
    require(actual == FILES, "G11 arena raw inventory is missing or extra")
    total = 0
    pins = {}

    def raw(name, maximum=4 * 1024**2):
        nonlocal total
        guard()
        path = root / name
        require(path.stat().st_size <= maximum, "G11 arena artifact exceeds byte cap")
        value = path.read_bytes()
        require(len(value) <= maximum, "G11 arena artifact grew during replay")
        return value

    for name in sorted(FILES):
        value = raw(name, 64 * 1024**2 if name == "engine" else 4 * 1024**2)
        total += len(value)
        require(total <= 128 * 1024**2, "G11 arena aggregate byte cap exceeded")
        pins[name] = hashlib.sha256(value).hexdigest()

    def document(name):
        return strict_json(raw(name))

    config = document("CONFIG.json")
    admit(config, expected_engine, expected_commit)
    require(
        pins["engine"] == expected_engine
        and pins["OPENINGS.json"] == config["openings_sha256"],
        "G11 arena saved engine or opening bytes differ",
    )
    stopped = document("KILL.json")
    require(
        type(stopped.get("signal")) is int
        and stopped["signal"] == 9
        and type(stopped.get("actual_exit")) is int
        and stopped["actual_exit"] == -9
        and type(stopped.get("pid")) is int
        and stopped["pid"] > 0,
        "G11 arena requires the actual forced SIGKILL exit",
    )
    signal_ns, reaped_ns = stopped.get("signal_monotonic_ns"), stopped.get(
        "reaped_monotonic_ns"
    )
    require(
        type(signal_ns) is int
        and type(reaped_ns) is int
        and signal_ns > 0
        and 0 <= reaped_ns - signal_ns <= 5_000_000_000,
        "G11 arena forced child was not reaped inside its bounded window",
    )
    digest = pins["before/000000-0.json"]
    ready = document("arena/RECOVERY_READY.json")
    require(
        typed_equal(
            ready,
            {
                "schema": "caissa-arena-commit-barrier-v1",
                "pair": 0,
                "reverse": 0,
                "game_sha256": digest,
            },
        )
        and stopped.get("committed_game_sha256") == digest
        and pins["arena/games/000000-0.json"] == digest,
        "G11 arena changed its protected committed game or boundary identity",
    )
    require(
        raw("partial-before/000000-0.pgn.tmp") == b'[Event "torn'
        and raw("partial-before/000000-1.json.tmp") == b'{"torn":',
        "G11 arena lacks its exact torn-write fixtures",
    )
    identity = document("arena/CONFIG.json")
    original = document("ARENA_INPUT.json")
    require(
        typed_equal(identity["config"], original),
        "G11 arena resumed with changed actor configuration",
    )
    require(
        original.get("profile") == "recovery-diagnostic-v2"
        and all(
            type(original.get(k)) is int and original[k] == v
            for k, v in {
                "pairs": 2,
                "nodes": 2000,
                "max_plies": 512,
                "warmup_nodes": 1,
            }.items()
        )
        and "milliseconds" not in original,
        "G11 arena recovery workload differs",
    )
    for role in ["candidate", "opponent"]:
        actor = identity["executables"][role]
        require(
            actor["executable"] == expected_engine
            and typed_equal(
                actor["options"], {"Threads": 1, "Hash": 1, "Use Neural": False}
            )
            and typed_equal(actor["options"], original[role]["options"])
            and typed_equal(actor["command"], original[role]["command"])
            and isinstance(actor["command"], list)
            and len(actor["command"]) == 1
            and "network_sha256" not in actor,
            "G11 arena control or program differs",
        )
    require(
        identity["executables"]["candidate"]["command"]
        == identity["executables"]["opponent"]["command"],
        "G11 arena used different search executables",
    )
    manifest = document("OPENINGS.json")
    require(
        manifest.get("schema") == "caissa-recovery-openings-v1"
        and len(manifest["openings"]) == 2,
        "G11 arena opening inventory differs",
    )
    for pair in range(2):
        item = document(f"arena/pairs/{pair:06d}.json")
        opening = manifest["openings"][pair]
        initial = chess.Board(opening["fen"]).fen(en_passant="fen")
        for game in item["games"]:
            require(
                game["opening_id"] == opening["id"]
                and game["initial"] == initial
                and game["opening_plies"] == len(opening["moves"])
                and game["moves"][: game["opening_plies"]] == opening["moves"],
                "G11 arena changed its opening prefix or initial board",
            )
    replay = journals(root / "arena", maximum_seconds=maximum_seconds, tick=guard)
    statistics = verify_campaign(
        root / "arena", root / "OPENINGS.json", expected_engine, tick=guard
    )
    require(
        replay["game_journals"] == 4 and statistics["statistics"]["games"] == 4,
        "G11 arena recovery lost or duplicated a finished game",
    )
    finish = document("FINISHED.json")
    end = finish.get("completed_unix")
    elapsed = finish.get("elapsed_seconds")
    require(
        all(type(v) in {int, float} and math.isfinite(v) for v in [end, elapsed])
        and config["started_unix"] <= end <= config["deadline_unix"]
        and 0 < elapsed <= 120,
        "G11 arena run escaped its original deadline",
    )
    native = None
    if native_output is not None:
        native = native_resume(
            root,
            native_output,
            identity,
            expected_engine,
            guard,
            lambda: min(
                maximum_seconds - (time.monotonic() - started),
                maximum_seconds - (time.time() - wall),
            ),
        )
    for name, expected in pins.items():
        require(
            hashlib.sha256(
                raw(name, 64 * 1024**2 if name == "engine" else 4 * 1024**2)
            ).hexdigest()
            == expected,
            "G11 arena raw evidence changed during independent replay",
        )
    return {
        "status": "passed",
        "component": "arena",
        "engine_sha256": expected_engine,
        "source_commit": expected_commit,
        "actual_forced_exit": -9,
        "protected_committed_games": 1,
        "reconstructed_games": 4,
        "reconstructed_pairs": 2,
        "reconstructed_pgns": 4,
        "torn_write_fixtures": 2,
        "component_pass": native is not None,
        "native_resumption": native,
        "raw_reconstruction_passed": True,
        "full_G11_certified": False,
        "full_acceptance": False,
        "scope": "Actual forced arena interruption and independent partial-pair/game/PGN reconstruction; training and data recovery remain separate",
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("evidence", type=Path)
    parser.add_argument("--engine-sha256", required=True)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--maximum-seconds", type=float, default=60)
    parser.add_argument("--native-output", type=Path)
    args = parser.parse_args()
    try:
        result = verify(
            args.evidence,
            args.engine_sha256,
            args.source_commit,
            args.maximum_seconds,
            native_output=args.native_output,
        )
    except (ValueError, KeyError, OSError, TypeError) as error:
        print(
            json.dumps(
                {"status": "rejected", "reason": str(error), "full_acceptance": False}
            )
        )
        raise SystemExit(1)
    print(json.dumps(result))


if __name__ == "__main__":
    main()
