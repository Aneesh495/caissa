"""Frozen resource profiles with legal PV replay and actual process RSS samples."""

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


class ResidentMemory:
    def __init__(self, process):
        self.process = process
        self.values = []
        self.stopped = threading.Event()
        self.error = None
        self.thread = threading.Thread(target=self.sample, daemon=True)

    def sample(self):
        try:
            self.sample_loop()
        except BaseException as error:
            self.error = error

    def sample_loop(self):
        while not self.stopped.is_set():
            result = subprocess.run(
                ["ps", "-o", "rss=", "-p", str(self.process.pid)],
                capture_output=True,
                text=True,
                timeout=1,
            )
            if result.returncode == 0 and result.stdout.strip():
                self.values.append(int(result.stdout.strip()) * 1024)
            self.stopped.wait(0.02)

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *_):
        self.stopped.set()
        self.thread.join(timeout=2)
        if self.thread.is_alive():
            raise RuntimeError("resident memory sampler did not finish")
        if self.error is not None:
            raise self.error
        if not self.values:
            raise ValueError("resident memory measurement is empty")


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


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--engine", type=Path, default=Path("build/caissa"))
    parser.add_argument("--network", type=Path, required=True)
    parser.add_argument("--config", type=Path, default=Path("config/performance.json"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--load-note", required=True)
    parser.add_argument("--diagnostic", action="store_true")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    config = json.loads(args.config.read_text())
    if (
        config["schema"] != "caissa-performance-v1"
        or not 20 <= config["milliseconds"] <= 10000
        or not 1 <= config["repeats"] <= 20
    ):
        raise ValueError("unsupported frozen profile")
    if any(t not in [1, 2, 4, 8] for t in config["threads"]) or not config["positions"]:
        raise ValueError("unsupported threads or empty profile")
    engine = str(args.engine.resolve())
    network = str(args.network.resolve())
    start = time.time()
    record = {
        "schema": "caissa-performance-run-v1",
        "profile": "diagnostic" if args.diagnostic else "full-performance-unverified",
        "engine_sha256": digest(engine),
        "network_sha256": digest(network),
        "config_sha256": digest(args.config),
        "config": config,
        "platform": platform.platform(),
        "cpu_count": os.cpu_count(),
        "load_note": args.load_note,
        "started_unix": start,
    }
    atomic_json(args.output / "CONFIG.json", record)
    profiles = []
    with (args.output / "measurements.jsonl").open("w") as log:
        for evaluation in [
            "classical",
            "neural-native",
            "neural-scalar",
            "neural-blend",
        ]:
            for threads in config["threads"]:
                options = {
                    "Hash": config["hash_mib"],
                    "Threads": threads,
                    "Search Stats": True,
                }
                if evaluation != "classical":
                    options.update(
                        {
                            "EvalFile": network,
                            "Use Neural": True,
                            "Scalar Neural": evaluation == "neural-scalar",
                            "Neural Weight": (
                                10 if evaluation == "neural-blend" else 100
                            ),
                        }
                    )
                rows = []
                with (
                    UciClient([engine], options, warmup_nodes=1) as client,
                    ResidentMemory(client.process) as memory,
                ):
                    for repeat in range(config["repeats"]):
                        for position in config["positions"]:
                            client.send("ucinewgame")
                            client.send("isready")
                            client.until("readyok", 5)
                            move, elapsed, lines = client.play(
                                position["fen"], [], milliseconds=config["milliseconds"]
                            )
                            observed = info(lines)
                            replay(position["fen"], move, observed["pv"])
                            row = {
                                "evaluation": evaluation,
                                "threads": threads,
                                "repeat": repeat,
                                "position": position["id"],
                                "fen": position["fen"],
                                "bestmove": move,
                                "roundtrip_ms": elapsed,
                                "observed": observed,
                                "uci": lines,
                            }
                            log.write(json.dumps(row, separators=(",", ":")) + "\n")
                            log.flush()
                            rows.append(row)
                grouped = []
                for position in config["positions"]:
                    subset = [row for row in rows if row["position"] == position["id"]]
                    grouped.append(
                        {
                            "position": position["id"],
                            "searches": len(subset),
                            "roundtrip_ms": percentiles(
                                [r["roundtrip_ms"] for r in subset]
                            ),
                            "mean_depth": statistics.mean(
                                r["observed"].get("depth", 0) for r in subset
                            ),
                            "mean_visited_nodes": statistics.mean(
                                r["observed"].get("stats", {}).get("visited_nodes", 0)
                                for r in subset
                            ),
                            "mean_useful_nodes": statistics.mean(
                                r["observed"]
                                .get("stats", {})
                                .get("completed_depth_nodes", 0)
                                for r in subset
                            ),
                        }
                    )
                profiles.append(
                    {
                        "evaluation": evaluation,
                        "threads": threads,
                        "searches": len(rows),
                        "per_position": grouped,
                        "roundtrip_ms": percentiles(
                            [row["roundtrip_ms"] for row in rows]
                        ),
                        "maximum_resident_bytes": max(memory.values, default=None),
                        "rss_samples": len(memory.values),
                        "mean_completed_depth": statistics.mean(
                            row["observed"].get("depth", 0) for row in rows
                        ),
                        "mean_visited_nodes": statistics.mean(
                            row["observed"].get("stats", {}).get("visited_nodes", 0)
                            for row in rows
                        ),
                        "mean_useful_nodes": statistics.mean(
                            row["observed"]
                            .get("stats", {})
                            .get("completed_depth_nodes", 0)
                            for row in rows
                        ),
                    }
                )
                print(json.dumps(profiles[-1]), flush=True)
    parity = []
    for position in config["positions"]:
        cases = []
        for scalar in [False, True]:
            with UciClient(
                [engine],
                {
                    "Hash": config["hash_mib"],
                    "Threads": 1,
                    "EvalFile": network,
                    "Use Neural": True,
                    "Scalar Neural": scalar,
                    "Search Stats": True,
                },
                warmup_nodes=1,
            ) as client:
                move, elapsed, lines = client.play(position["fen"], [], nodes=10000)
                observed = info(lines)
                replay(position["fen"], move, observed["pv"])
                semantic = {
                    key: observed.get(key)
                    for key in [
                        "depth",
                        "seldepth",
                        "nodes",
                        "score_type",
                        "score",
                        "pv",
                    ]
                }
                cases.append(
                    {
                        "scalar": scalar,
                        "bestmove": move,
                        "semantic": semantic,
                        "uci": lines,
                    }
                )
        if (
            cases[0]["bestmove"] != cases[1]["bestmove"]
            or cases[0]["semantic"] != cases[1]["semantic"]
        ):
            raise ValueError("scalar and optimized fixed-node search semantics differ")
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
    with (args.output / "latency.jsonl").open("w") as log:
        for active in [False, True]:
            options = {"Hash": config["hash_mib"], "Threads": max(config["threads"])}
            values = []
            with UciClient([engine], options, warmup_nodes=1) as client:
                if active:
                    client.send("position startpos")
                    client.send("go infinite")
                for index in range(config["latency_samples"]):
                    begin = time.monotonic_ns()
                    client.send("isready")
                    client.until("readyok", 5)
                    elapsed = (time.monotonic_ns() - begin) / 1e6
                    values.append(elapsed)
                    log.write(
                        json.dumps(
                            {"active": active, "index": index, "roundtrip_ms": elapsed}
                        )
                        + "\n"
                    )
                if active:
                    begin = time.monotonic_ns()
                    client.send("stop")
                    client.until("bestmove ", 5)
                    latency["stop_ms"] = (time.monotonic_ns() - begin) / 1e6
            latency["active" if active else "idle"] = percentiles(values)
    if (
        digest(engine) != record["engine_sha256"]
        or digest(network) != record["network_sha256"]
    ):
        raise ValueError("profile executable or network changed during measurement")
    summary = {
        "schema": "caissa-performance-summary-v1",
        "profile": record["profile"],
        "profiles": profiles,
        "latency": latency,
        "wall_seconds": time.time() - start,
        "load_note": args.load_note,
        "measurements_sha256": digest(args.output / "measurements.jsonl"),
        "latency_sha256": digest(args.output / "latency.jsonl"),
        "fixed_node_parity_positions": len(parity),
        "correctness_sha256": digest(args.output / "correctness.json"),
    }
    atomic_json(args.output / "SUMMARY.json", summary)
    print(json.dumps(summary))


if __name__ == "__main__":
    main()
