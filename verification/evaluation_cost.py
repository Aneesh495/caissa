"""Replay exact cache experiments without producer parsing or transport code."""

import argparse
import contextlib
import hashlib
import json
import math
import signal
import subprocess
import tempfile
import statistics
import time
from pathlib import Path

import chess

from verification.native_session import NativeSession
from verification.protocol import read_json
from verification.acquisition import sha


def require(condition, reason):
    if not condition:
        raise ValueError(reason)


def parse(lines, fen):
    board = chess.Board(fen)
    infos = []
    stats = None
    for line in lines:
        require(
            type(line) is str and len(line) <= 16384, "malformed cost protocol line"
        )
        if line.startswith("info depth "):
            tokens = line.split()
            row = {}
            for key in ["depth", "seldepth", "nodes", "time", "nps", "hashfull"]:
                if key in tokens:
                    row[key] = int(tokens[tokens.index(key) + 1])
            at = tokens.index("score")
            row["score_type"] = tokens[at + 1]
            row["score"] = int(tokens[at + 2])
            row["pv"] = tokens[tokens.index("pv") + 1 :] if "pv" in tokens else []
            replay = board.copy(stack=False)
            for text in row["pv"]:
                move = chess.Move.from_uci(text)
                require(
                    move in replay.legal_moves, "cost observation contains illegal PV"
                )
                replay.push(move)
            infos.append(row)
        if line.startswith("info string stats "):
            tokens = line.split()[3:]
            require(len(tokens) % 2 == 0, "cost statistics field layout differs")
            stats = {tokens[i]: int(tokens[i + 1]) for i in range(0, len(tokens), 2)}
    require(
        lines and lines[-1].startswith("bestmove ") and stats is not None,
        "cost observation lacks a terminal native response or statistics",
    )
    move = lines[-1].split()[1]
    require(chess.Move.from_uci(move) in board.legal_moves, "cost best move is illegal")
    if not infos:
        require(
            stats["completed_depth_nodes"] == 0,
            "missing PV concealed a completed depth",
        )
    result = infos[-1] if infos else {"pv": []}
    result["stats"] = stats
    return move, result


def verify(
    root, engine, network, positions_path, maximum_seconds=600, replay_output=None
):
    start = time.monotonic()
    wall = time.time()
    deadline = wall + maximum_seconds
    for path in [root / "CONFIG.json", root / "SUMMARY.json", positions_path]:
        require(0 < path.stat().st_size <= 1024 * 1024, "cost metadata byte ceiling")
    require(
        0 < (root / "observations.jsonl").stat().st_size <= 128 * 1024 * 1024,
        "cost observation byte ceiling",
    )
    config = read_json((root / "CONFIG.json").read_text())
    summary = read_json((root / "SUMMARY.json").read_text())
    require(
        len(config["inputs"]) == 3
        and set(config["inputs"].values())
        == {sha(p) for p in [engine, network, positions_path]},
        "cost input identity differs",
    )
    if replay_output is not None:
        require(
            not Path(replay_output).resolve().is_relative_to(root.resolve()),
            "independent replay output must be outside immutable cost evidence",
        )
    positions = read_json(positions_path.read_text())["positions"]
    by_id = {p["id"]: p for p in positions}
    modes = {
        "classical-exact": [0, False, False],
        "classical-cache": [0, False, True],
        "mixture-exact": [10, False, False],
        "mixture-cache": [10, False, True],
        "neural-exact": [100, False, False],
        "neural-cache": [100, False, True],
    }
    require(
        config["modes"] == modes
        and config["threads"] == 1
        and config["hash_mib"] == 16
        and config["warmup_nodes"] == 1,
        "unsupported exact cost mode/resource contract",
    )
    require(
        1000 <= config["nodes"] <= 100000 and 1 <= config["repeats"] <= 10,
        "cost workload outside finite contract",
    )
    require(
        sha(root / "observations.jsonl") == summary["observations_sha256"],
        "cost observation bytes changed",
    )
    rows = [
        read_json(line)
        for line in (root / "observations.jsonl").read_text().splitlines()
    ]
    require(
        len(rows)
        == len(modes) * len(positions) * config["repeats"]
        == summary["searches"],
        "cost sample is incomplete",
    )
    require(
        summary["status"] == "passed"
        and 0 <= summary["seconds"] <= config["maximum_seconds"],
        "cost summary status or duration differs",
    )
    seen = set()
    previous = 0
    replayed = 0
    logical = ["depth", "seldepth", "nodes", "score_type", "score", "pv"]
    counters = [
        "visited_nodes",
        "completed_depth_nodes",
        "qnodes",
        "tt_hits",
        "tt_cutoffs",
        "beta_cutoffs",
        "null_cutoffs",
        "lmr",
        "researches",
        "futility",
        "eval_calls",
    ]
    with (
        contextlib.ExitStack() as stack,
        (
            Path(replay_output).open("x")
            if replay_output
            else tempfile.TemporaryFile(mode="w+")
        ) as replay_log,
    ):
        clients = {}
        for name, (weight, bounded, cached) in modes.items():
            options = {
                "Hash": 16,
                "Threads": 1,
                "Search Stats": True,
                "Evaluation Cache": cached,
                "Neural Bounds": bounded,
            }
            if weight:
                options.update(
                    {
                        "EvalFile": str(network.resolve()),
                        "Neural Weight": weight,
                        "Use Neural": True,
                    }
                )
            clients[name] = stack.enter_context(
                NativeSession(engine, options, deadline)
            )
        for row in rows:
            require(
                time.monotonic() - start < maximum_seconds and time.time() < deadline,
                "cumulative independent cost deadline",
            )
            key = (row["repeat"], row["position"], row["mode"])
            require(
                key not in seen
                and row["mode"] in modes
                and row["position"] in by_id
                and 0 <= row["repeat"] < config["repeats"],
                "duplicate or invalid cost identity",
            )
            seen.add(key)
            require(
                row["fen"] == by_id[row["position"]]["fen"],
                "cost input FEN differs from frozen manifest",
            )
            request = row["request"]
            measured = (
                request["completed_monotonic_ns"] - request["started_monotonic_ns"]
            ) / 1e6
            require(
                request["started_monotonic_ns"] >= previous
                and request["completed_monotonic_ns"] >= request["started_monotonic_ns"]
                and abs(measured - row["roundtrip_ms"]) < 1e-9,
                "cost timing differs from recorded monotonic requests",
            )
            previous = request["completed_monotonic_ns"]
            require(
                request["position"] == "position fen " + row["fen"]
                and request["go"] == "go nodes " + str(config["nodes"]),
                "cost request changed its position or node budget",
            )
            move, observed = parse(row["uci"], row["fen"])
            require(
                move == row["bestmove"] and observed == row["observed"],
                "cost parsed fields differ from actual saved native output",
            )
            current = clients[row["mode"]].search(row["fen"], config["nodes"])
            new_move, new_observed = parse(current, row["fen"])
            require(
                new_move == move
                and all(new_observed.get(k) == observed.get(k) for k in logical)
                and all(
                    new_observed["stats"][k] == observed["stats"][k]
                    for k in counters
                    + [
                        "neural_evaluations",
                        "neural_bound_cutoffs",
                        "evaluation_cache_hits",
                        "evaluation_cache_bytes",
                    ]
                ),
                "independent saved-engine cost replay differs",
            )
            replay_log.write(
                json.dumps({"identity": key, "actual_uci": current}) + "\n"
            )
            replayed += 1
    for mode in modes:
        subset = [r for r in rows if r["mode"] == mode]
        metrics = {
            "roundtrip_ms": sum(r["roundtrip_ms"] for r in subset),
            "visited_nodes": sum(
                r["observed"]["stats"]["visited_nodes"] for r in subset
            ),
            "neural_evaluations": sum(
                r["observed"]["stats"]["neural_evaluations"] for r in subset
            ),
            "certified_cutoffs": sum(
                r["observed"]["stats"]["neural_bound_cutoffs"] for r in subset
            ),
            "evaluator_ns": sum(r["observed"]["stats"]["eval_ns"] for r in subset),
            "evaluation_cache_hits": sum(
                r["observed"]["stats"]["evaluation_cache_hits"] for r in subset
            ),
            "evaluation_requests": sum(
                r["observed"]["stats"]["eval_calls"] for r in subset
            ),
        }
        for name, value in metrics.items():
            require(
                abs(summary["modes"][mode][name] - value) < 1e-7,
                "independent cost aggregate differs: " + name,
            )
    ratios = {}
    for prefix in ["classical", "mixture", "neural"]:
        values = []
        for repeat in range(config["repeats"]):
            for position in positions:
                pair = {
                    r["mode"]: r
                    for r in rows
                    if r["repeat"] == repeat and r["position"] == position["id"]
                }
                left, right = pair[prefix + "-cache"], pair[prefix + "-exact"]
                require(
                    left["bestmove"] == right["bestmove"]
                    and all(
                        left["observed"].get(k) == right["observed"].get(k)
                        for k in logical
                    )
                    and all(
                        left["observed"]["stats"][k] == right["observed"]["stats"][k]
                        for k in counters
                    ),
                    "cache changed an independently checked fixed-node tree",
                )
                values.append(left["roundtrip_ms"] / right["roundtrip_ms"])
        ratios[prefix] = {
            "median": statistics.median(values),
            "minimum": min(values),
            "maximum": max(values),
        }
        for key, value in ratios[prefix].items():
            require(
                abs(
                    summary["paired_cache_over_exact_roundtrip_ratio"][prefix][key]
                    - value
                )
                < 1e-12,
                "independent cost ratio differs",
            )
    return {
        "status": "passed",
        "independently_replayed_searches": replayed,
        "searches_without_completed_depth": sum(
            "depth" not in r["observed"] for r in rows
        ),
        "engine_sha256": sha(engine),
        "network_sha256": sha(network),
        "paired_cache_over_exact_roundtrip_ratio": ratios,
        "scope": "Exact fixed-node semantics and observed cost recomputation; no Elo or full systems acceptance",
        "full_acceptance": False,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("evidence", type=Path)
    parser.add_argument("--engine", type=Path, required=True)
    parser.add_argument("--network", type=Path, required=True)
    parser.add_argument(
        "--positions", type=Path, default=Path("config/performance.json")
    )
    parser.add_argument("--max-seconds", type=float, default=600)
    parser.add_argument("--replay-output", type=Path)
    args = parser.parse_args()

    def interrupted(signum, frame):
        raise InterruptedError("independent cost verifier interrupted")

    signal.signal(signal.SIGTERM, interrupted)
    try:
        require(
            math.isfinite(args.max_seconds) and 0 < args.max_seconds <= 900,
            "finite independent cost duration required",
        )
        print(
            json.dumps(
                verify(
                    args.evidence,
                    args.engine,
                    args.network,
                    args.positions,
                    args.max_seconds,
                    args.replay_output,
                )
            )
        )
        return 0
    except (
        ValueError,
        OSError,
        KeyError,
        IndexError,
        TypeError,
        subprocess.SubprocessError,
    ) as error:
        print(
            json.dumps(
                {"status": "rejected", "reason": str(error), "full_acceptance": False}
            )
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
