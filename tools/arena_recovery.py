"""Capture an actual killed partial pair and preserve all recovery evidence.

This bounded four-game experiment never changes a strength sample, training
run or selected model. Training/data recovery are separate G11 components.
"""

import argparse
import hashlib
import json
import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

from tools.campaign_process import atomic
from tools.host_lease import HostLease
from tools.heuristic_study import avoid_decisive_matches
from tools.recovery_scope import tree_bytes


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def execute(engine, output, openings, maximum_seconds=120):
    avoid_decisive_matches()
    if maximum_seconds != 120:
        raise ValueError("arena recovery has one fixed 120-second ceiling")
    engine, output, openings = (Path(x).resolve() for x in [engine, output, openings])
    if output.exists():
        raise ValueError("arena recovery output already exists; preserve it")
    lease = HostLease(Path("runs"))
    process = None
    start, wall = time.monotonic(), time.time()
    output.mkdir(parents=True)

    def remaining():
        lease.check()
        value = min(120 - (time.monotonic() - start), wall + 120 - time.time())
        if value <= 0:
            raise TimeoutError("arena recovery original wall/active ceiling exhausted")
        if shutil.disk_usage(output).free < 10 * 1024**3:
            raise ValueError("arena recovery free-space reserve exhausted")
        if tree_bytes(output) > 128 * 1024**2:
            raise ValueError("arena recovery additional output ceiling exhausted")
        return value

    try:
        binary = output / "engine"
        shutil.copyfile(engine, binary)
        binary.chmod(0o755)
        shutil.copyfile(openings, output / "OPENINGS.json")
        config = {
            "profile": "recovery-diagnostic-v2",
            "candidate": {
                "name": "Caissa recovery A",
                "command": [str(binary)],
                "options": {"Threads": 1, "Hash": 1, "Use Neural": False},
            },
            "opponent": {
                "name": "Caissa recovery B",
                "command": [str(binary)],
                "options": {"Threads": 1, "Hash": 1, "Use Neural": False},
            },
            "openings": str(output / "OPENINGS.json"),
            "pairs": 2,
            "nodes": 2000,
            "max_plies": 512,
            "warmup_nodes": 1,
        }
        atomic(output / "ARENA_INPUT.json", config)
        atomic(
            output / "CONFIG.json",
            {
                "schema": "caissa-arena-recovery-observations-v1",
                "source_commit": subprocess.check_output(
                    ["git", "rev-parse", "HEAD"], text=True, timeout=5
                ).strip(),
                "engine_sha256": sha(binary),
                "openings_sha256": sha(output / "OPENINGS.json"),
                "maximum_seconds": 120,
                "maximum_output_bytes": 128 * 1024**2,
                "minimum_free_bytes": 10 * 1024**3,
                "started_unix": wall,
                "deadline_unix": wall + 120,
                "profile": "recovery-component-only",
                "full_G11_certified": False,
            },
        )
        arena = output / "arena"
        barrier = arena / "RECOVERY_READY.json"
        command = [
            sys.executable,
            "-m",
            "arena.run",
            str(output / "ARENA_INPUT.json"),
            str(arena),
            "--workers",
            "1",
        ]
        with (output / "interrupted.log").open("w") as stream:
            process = subprocess.Popen(
                command + ["--recovery-barrier", str(barrier)],
                stdout=stream,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
            until = time.monotonic() + min(35, remaining())
            while not barrier.exists():
                remaining()
                if process.poll() is not None:
                    raise ValueError("arena exited before its committed-game barrier")
                if time.monotonic() >= until:
                    raise TimeoutError("arena did not reach its bounded commit barrier")
                time.sleep(0.01)
            committed = arena / "games/000000-0.json"
            ready_hash = json.loads(barrier.read_text())["game_sha256"]
            if sha(committed) != ready_hash or list((arena / "pairs").glob("*.json")):
                raise ValueError("unexpected arena transaction at interruption")
            (output / "before").mkdir()
            shutil.copyfile(committed, output / "before/000000-0.json")
            signal_ns = time.monotonic_ns()
            os.killpg(process.pid, signal.SIGKILL)
            actual_exit = process.wait(timeout=min(5, remaining()))
            reaped_ns = time.monotonic_ns()
            if actual_exit != -signal.SIGKILL:
                raise ValueError("arena did not exit from the actual forced SIGKILL")
            if sorted(p.name for p in (arena / "games").iterdir()) != ["000000-0.json"]:
                raise ValueError(
                    "forced interruption missed its partial-pair transaction"
                )
            atomic(
                output / "KILL.json",
                {
                    "signal": 9,
                    "actual_exit": actual_exit,
                    "pid": process.pid,
                    "signal_monotonic_ns": signal_ns,
                    "reaped_monotonic_ns": reaped_ns,
                    "committed_game_sha256": ready_hash,
                },
            )
        process = None
        (output / "partial-before").mkdir()
        for name, content in [
            ("000000-0.pgn.tmp", '[Event "torn'),
            ("000000-1.json.tmp", '{"torn":'),
        ]:
            (arena / "games" / name).write_text(content)
            (output / "partial-before" / name).write_text(content)
        for name, cmd in [
            ("resumed", command),
            ("statistics", [sys.executable, "-m", "arena.statistics", str(arena)]),
        ]:
            with (output / (name + ".log")).open("w") as stream:
                subprocess.run(
                    cmd,
                    stdout=stream,
                    stderr=subprocess.STDOUT,
                    check=True,
                    timeout=remaining(),
                )
        if sha(committed) != ready_hash:
            raise ValueError("arena recovery changed the already committed game")
        remaining()
        atomic(
            output / "FINISHED.json",
            {
                "completed_unix": time.time(),
                "elapsed_seconds": time.monotonic() - start,
                "full_G11_certified": False,
                "full_acceptance": False,
            },
        )
        return {
            "status": "observed",
            "actual_forced_exit": actual_exit,
            "output": str(output),
            "full_G11_certified": False,
            "full_acceptance": False,
        }
    except BaseException as error:
        atomic(
            output / "FAILED.json",
            {"reason": str(error), "unix": time.time(), "full_acceptance": False},
        )
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
    parser.add_argument(
        "--openings", type=Path, default=Path("config/recovery-openings-v1.json")
    )
    args = parser.parse_args()
    print(json.dumps(execute(args.engine, args.output, args.openings)))


if __name__ == "__main__":
    main()
