"""Bounded resource profiles with raw RSS, request and latency evidence.

Timed observations describe their actual host load. They do not establish
parallel playing strength or complete-project acceptance.
"""

import argparse
import json
import os
import platform
import statistics
import subprocess
import threading
import time
from pathlib import Path

import chess
import numpy as np

from arena.client import UciClient
from training.corpus import atomic_json, digest


def percentiles(values):
    if not values:
        raise ValueError("empty performance measurement")
    return {
        key: float(np.quantile(values, value))
        for key, value in [("p50", 0.5), ("p95", 0.95), ("p99", 0.99)]
    } | {"max": max(values), "count": len(values)}


def info(lines):
    candidates = [line for line in lines if line.startswith("info depth ")]
    tokens = candidates[-1].split() if candidates else []
    result = {}
    for field in ["depth", "seldepth", "nodes", "time", "nps", "hashfull"]:
        if field in tokens:
            result[field] = int(tokens[tokens.index(field) + 1])
    if "score" in tokens:
        offset = tokens.index("score")
        result["score_type"], result["score"] = tokens[offset + 1], int(
            tokens[offset + 2]
        )
    result["pv"] = tokens[tokens.index("pv") + 1 :] if "pv" in tokens else []
    stats = [line for line in lines if line.startswith("info string stats ")]
    if stats:
        fields = stats[-1].split()[3:]
        if len(fields) % 2:
            raise ValueError("odd native statistics field count")
        result["stats"] = {
            fields[i]: int(fields[i + 1]) for i in range(0, len(fields), 2)
        }
    return result


def replay(fen, move, pv):
    board = chess.Board(fen)
    if move == "0000":
        if any(board.legal_moves) and not board.is_game_over(claim_draw=False):
            raise ValueError("profile returned null move in playable position")
    elif chess.Move.from_uci(move) not in board.legal_moves:
        raise ValueError("profile best move is illegal")
    for text in pv:
        candidate = chess.Move.from_uci(text)
        if candidate not in board.legal_moves:
            raise ValueError("profile PV is illegal")
        board.push(candidate)


class Budget:
    def __init__(self, seconds):
        if not 1 <= seconds <= 3600:
            raise ValueError("profile requires finite wall and active-time ceilings")
        self.started = time.time()
        self.deadline = self.started + seconds
        self.active_deadline = time.monotonic() + seconds

    def check(self):
        if time.time() >= self.deadline or time.monotonic() >= self.active_deadline:
            raise TimeoutError("resource profile cumulative deadline exhausted")


class ResidentMemory:
    def __init__(self, process, output, identity, budget):
        self.process, self.output, self.identity, self.budget = (
            process,
            output,
            identity,
            budget,
        )
        self.values = []
        self.stopped = threading.Event()
        self.error = None
        self.thread = threading.Thread(target=self.sample, daemon=True)

    def sample(self):
        try:
            with self.output.open("a") as log:
                while not self.stopped.is_set():
                    self.budget.check()
                    begin = time.monotonic_ns()
                    result = subprocess.run(
                        ["ps", "-o", "rss=", "-p", str(self.process.pid)],
                        capture_output=True,
                        text=True,
                        timeout=1,
                    )
                    if len(result.stdout) + len(result.stderr) > 4096:
                        raise ValueError("RSS subprocess response exceeds byte ceiling")
                    end = time.monotonic_ns()
                    value = (
                        int(result.stdout.strip()) * 1024
                        if result.returncode == 0 and result.stdout.strip()
                        else None
                    )
                    row = {
                        **self.identity,
                        "pid": self.process.pid,
                        "started_ns": begin,
                        "completed_ns": end,
                        "ps_exit": result.returncode,
                        "ps_stdout": result.stdout,
                        "ps_stderr": result.stderr,
                        "rss_bytes": value,
                    }
                    log.write(json.dumps(row, separators=(",", ":")) + "\n")
                    log.flush()
                    if value is not None:
                        if value <= 0:
                            raise ValueError("RSS measurement is nonpositive")
                        self.values.append(value)
                    if len(self.values) > 100000 or log.tell() > 32 * 1024 * 1024:
                        raise ValueError("RSS sample count or byte ceiling exhausted")
                    self.stopped.wait(0.02)
        except BaseException as error:
            self.error = error

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *_):
        self.stopped.set()
        self.thread.join(timeout=2)
        if self.thread.is_alive():
            raise RuntimeError("RSS sampler did not finish")
        if self.error is not None:
            raise self.error
        if not self.values:
            raise ValueError("RSS measurement is empty")


def validate(config):
    if (
        config["schema"] != "caissa-performance-v1"
        or type(config["milliseconds"]) is not int
        or not 20 <= config["milliseconds"] <= 10000
        or type(config["repeats"]) is not int
        or not 1 <= config["repeats"] <= 20
    ):
        raise ValueError("unsupported bounded resource workload")
    threads = config["threads"]
    if (
        not isinstance(threads, list)
        or not threads
        or len(set(threads)) != len(threads)
        or any(type(t) is not int or t not in (1, 2, 4, 8) for t in threads)
    ):
        raise ValueError("invalid or repeated profile threads")
    if (
        type(config["latency_samples"]) is not int
        or not 1 <= config["latency_samples"] <= 10000
        or type(config["hash_mib"]) is not int
        or not 1 <= config["hash_mib"] <= 1024
    ):
        raise ValueError("latency or hash resource ceiling exceeded")
    positions = config["positions"]
    if not 1 <= len(positions) <= 100 or len({p["id"] for p in positions}) != len(
        positions
    ):
        raise ValueError("invalid profile position inventory")
    for row in positions:
        board = chess.Board(row["fen"])
        if not board.is_valid() or not any(board.legal_moves):
            raise ValueError("profile requires valid playable positions")


def metrics(rows):
    stats = [row["observed"]["stats"] for row in rows]
    duration = sum(row["roundtrip_ms"] for row in rows) / 1000
    visited = sum(s["visited_nodes"] for s in stats)
    useful = sum(s["completed_depth_nodes"] for s in stats)
    calls = sum(s["eval_calls"] for s in stats)
    return {
        "searches": len(rows),
        "roundtrip_ms": percentiles([r["roundtrip_ms"] for r in rows]),
        "mean_depth": statistics.mean(r["observed"].get("depth", 0) for r in rows),
        "mean_visited_nodes": visited / len(rows),
        "mean_useful_nodes": useful / len(rows),
        "visited_nodes_per_second": visited / duration,
        "useful_nodes_per_second": useful / duration,
        "evaluator_ns_per_call": (
            sum(s["eval_ns"] for s in stats) / calls if calls else None
        ),
        "table_bytes": sorted({s["table_bytes"] for s in stats}),
        "evaluation_cache_bytes": sorted({s["evaluation_cache_bytes"] for s in stats}),
    }


def options(config, network, evaluation, threads, optimized):
    result = {
        "Hash": config["hash_mib"],
        "Threads": threads,
        "Search Stats": True,
        "Evaluation Cache": optimized,
        "Tactical Generation": optimized,
        "Neural Bounds": False,
        "Ordering Hints": False,
    }
    if evaluation != "classical":
        result.update(
            {
                "EvalFile": network,
                "Use Neural": True,
                "Scalar Neural": evaluation == "neural-scalar",
                "Neural Weight": 10 if evaluation == "neural-blend" else 100,
            }
        )
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--engine", type=Path, default=Path("build/caissa"))
    parser.add_argument("--network", type=Path, required=True)
    parser.add_argument("--config", type=Path, default=Path("config/performance.json"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--load-note", required=True)
    parser.add_argument("--diagnostic", action="store_true")
    parser.add_argument("--exact-optimizations", action="store_true")
    parser.add_argument("--maximum-seconds", type=int, default=1800)
    args = parser.parse_args()
    config = json.loads(args.config.read_text())
    validate(config)
    budget = Budget(args.maximum_seconds)
    args.output.mkdir(parents=True, exist_ok=False)
    engine, network = str(args.engine.resolve()), str(args.network.resolve())
    record = {
        "schema": "caissa-performance-run-v2",
        "profile": "diagnostic" if args.diagnostic else "full-performance-unverified",
        "engine_sha256": digest(engine),
        "network_sha256": digest(network),
        "config_sha256": digest(args.config),
        "config": config,
        "platform": platform.platform(),
        "cpu_count": os.cpu_count(),
        "load_note": args.load_note,
        "started_unix": budget.started,
        "maximum_seconds": args.maximum_seconds,
        "deadline_unix": budget.deadline,
        "exact_optimizations": args.exact_optimizations,
        "full_acceptance": False,
    }
    atomic_json(args.output / "CONFIG.json", record)
    sessions = []
    profiles = []

    def connect(evaluation, threads):
        budget.check()
        selected = options(
            config, network, evaluation, threads, args.exact_optimizations
        )
        client = UciClient([engine], selected, warmup_nodes=1)
        sessions.append(
            {
                "id": len(sessions),
                "evaluation": evaluation,
                "threads": threads,
                "pid": client.process.pid,
                "options": selected,
                "handshake": client.handshake,
                "configuration_commands": client.configuration_commands,
                "started_ns": time.monotonic_ns(),
            }
        )
        atomic_json(args.output / "SESSIONS.json", sessions)
        return client

    try:
        with (args.output / "measurements.jsonl").open("x") as log:
            expected = (
                4
                * len(config["threads"])
                * config["repeats"]
                * len(config["positions"])
            )
            completed = 0
            for evaluation in [
                "classical",
                "neural-native",
                "neural-scalar",
                "neural-blend",
            ]:
                for threads in config["threads"]:
                    rows = []
                    with connect(evaluation, threads) as client:
                        session = sessions[-1]["id"]
                        with ResidentMemory(
                            client.process,
                            args.output / "memory.jsonl",
                            {
                                "session": session,
                                "evaluation": evaluation,
                                "threads": threads,
                            },
                            budget,
                        ) as memory:
                            for repeat in range(config["repeats"]):
                                for position in config["positions"]:
                                    budget.check()
                                    client.send("ucinewgame")
                                    client.send("isready")
                                    client.until("readyok", 5)
                                    move, elapsed, lines = client.play(
                                        position["fen"],
                                        [],
                                        milliseconds=config["milliseconds"],
                                    )
                                    observed = info(lines)
                                    replay(position["fen"], move, observed["pv"])
                                    row = {
                                        "session": session,
                                        "evaluation": evaluation,
                                        "threads": threads,
                                        "repeat": repeat,
                                        "position": position["id"],
                                        "fen": position["fen"],
                                        "bestmove": move,
                                        "roundtrip_ms": elapsed,
                                        "request": client.last_request,
                                        "observed": observed,
                                        "uci": lines,
                                    }
                                    log.write(
                                        json.dumps(row, separators=(",", ":")) + "\n"
                                    )
                                    log.flush()
                                    rows.append(row)
                                    completed += 1
                                    atomic_json(
                                        args.output / "PROGRESS.json",
                                        {
                                            "phase": "timed-searches",
                                            "completed": completed,
                                            "expected": expected,
                                            "wall_seconds": time.time()
                                            - budget.started,
                                            "deadline_unix": budget.deadline,
                                        },
                                    )
                                    if log.tell() > 128 * 1024 * 1024:
                                        raise ValueError(
                                            "measurement byte ceiling exhausted"
                                        )
                        sessions[-1]["completed_ns"] = time.monotonic_ns()
                        atomic_json(args.output / "SESSIONS.json", sessions)
                    profiles.append(
                        {
                            "evaluation": evaluation,
                            "threads": threads,
                            **metrics(rows),
                            "maximum_resident_bytes": max(memory.values),
                            "rss_samples": len(memory.values),
                            "per_position": [
                                {
                                    "position": position["id"],
                                    **metrics(
                                        [
                                            row
                                            for row in rows
                                            if row["position"] == position["id"]
                                        ]
                                    ),
                                }
                                for position in config["positions"]
                            ],
                        }
                    )
        parity = []
        for position in config["positions"]:
            cases = []
            for evaluation in ["neural-native", "neural-scalar"]:
                with connect(evaluation, 1) as client:
                    move, elapsed, lines = client.play(position["fen"], [], nodes=10000)
                    observed = info(lines)
                    replay(position["fen"], move, observed["pv"])
                    cases.append(
                        {
                            "session": sessions[-1]["id"],
                            "scalar": evaluation == "neural-scalar",
                            "bestmove": move,
                            "semantic": {
                                key: observed.get(key)
                                for key in [
                                    "depth",
                                    "seldepth",
                                    "nodes",
                                    "score_type",
                                    "score",
                                    "pv",
                                ]
                            },
                            "request": client.last_request,
                            "uci": lines,
                        }
                    )
            if (
                cases[0]["bestmove"] != cases[1]["bestmove"]
                or cases[0]["semantic"] != cases[1]["semantic"]
            ):
                raise ValueError("scalar/optimized fixed-node search differs")
            parity.append(
                {
                    "position": position["id"],
                    "fen": position["fen"],
                    "node_budget": 10000,
                    "cases": cases,
                }
            )
            atomic_json(args.output / "correctness.json", parity)
        latency = {}
        with (args.output / "latency.jsonl").open("x") as log:
            for active in [False, True]:
                values = []
                with connect("classical", max(config["threads"])) as client:
                    session = sessions[-1]["id"]
                    if active:
                        client.send("position startpos")
                        client.send("go infinite")
                    for index in range(config["latency_samples"]):
                        budget.check()
                        begin = time.monotonic_ns()
                        client.send("isready")
                        reply = client.until("readyok", 5)
                        end = time.monotonic_ns()
                        elapsed = (end - begin) / 1e6
                        values.append(elapsed)
                        log.write(
                            json.dumps(
                                {
                                    "session": session,
                                    "active": active,
                                    "index": index,
                                    "command": "isready",
                                    "started_ns": begin,
                                    "completed_ns": end,
                                    "roundtrip_ms": elapsed,
                                    "reply": reply,
                                },
                                separators=(",", ":"),
                            )
                            + "\n"
                        )
                        if log.tell() > 32 * 1024 * 1024:
                            raise ValueError("latency byte ceiling exhausted")
                    if active:
                        begin = time.monotonic_ns()
                        client.send("stop")
                        reply = client.until("bestmove ", 5)
                        end = time.monotonic_ns()
                        latency["stop_ms"] = (end - begin) / 1e6
                        log.write(
                            json.dumps(
                                {
                                    "session": session,
                                    "active": True,
                                    "command": "stop",
                                    "started_ns": begin,
                                    "completed_ns": end,
                                    "roundtrip_ms": latency["stop_ms"],
                                    "reply": reply,
                                },
                                separators=(",", ":"),
                            )
                            + "\n"
                        )
                latency["active" if active else "idle"] = percentiles(values)
        budget.check()
        if (
            digest(engine) != record["engine_sha256"]
            or digest(network) != record["network_sha256"]
            or digest(args.config) != record["config_sha256"]
        ):
            raise ValueError("profile source inputs changed")
        summary = {
            "schema": "caissa-performance-summary-v2",
            "profile": record["profile"],
            "profiles": profiles,
            "latency": latency,
            "wall_seconds": time.time() - budget.started,
            "full_acceptance": False,
            "files": {
                name: digest(args.output / name)
                for name in [
                    "measurements.jsonl",
                    "memory.jsonl",
                    "latency.jsonl",
                    "correctness.json",
                    "SESSIONS.json",
                ]
            },
            "fixed_node_parity_positions": len(parity),
        }
        atomic_json(args.output / "SUMMARY.json", summary)
        print(json.dumps(summary))
        return 0
    except BaseException as error:
        atomic_json(
            args.output / "FAILED.json",
            {
                "exception": type(error).__name__,
                "reason": str(error),
                "deadline_unix": budget.deadline,
                "wall_seconds": time.time() - budget.started,
                "full_acceptance": False,
            },
        )
        raise


if __name__ == "__main__":
    raise SystemExit(main())
