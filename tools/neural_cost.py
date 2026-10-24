"""Paired fixed-node evaluator cost profiles with all native observations saved."""

import argparse
import hashlib
import json
import platform
import random
import statistics
import time
from contextlib import ExitStack
from pathlib import Path

from arena.client import UciClient
from tools.campaign_process import atomic
from tools.performance import info, replay


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--engine", required=True, type=Path)
    parser.add_argument("--network", required=True, type=Path)
    parser.add_argument(
        "--positions", type=Path, default=Path("config/performance.json")
    )
    parser.add_argument("--nodes", type=int, default=20000)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--load-note", required=True)
    parser.add_argument("--cache-comparison", action="store_true")
    parser.add_argument("--combined-comparison", action="store_true")
    args = parser.parse_args()
    if args.cache_comparison and args.combined_comparison:
        parser.error("select one exact optimization comparison")
    exact_comparison = args.cache_comparison or args.combined_comparison
    variant = "combined" if args.combined_comparison else "cache"
    if not 1000 <= args.nodes <= 100000 or not 1 <= args.repeats <= 10:
        parser.error("fixed workload exceeds diagnostic bounds")
    positions = json.loads(args.positions.read_text())["positions"]
    if not 1 <= len(positions) <= 100 or len({p["id"] for p in positions}) != len(
        positions
    ):
        raise ValueError("position inventory is empty, duplicated or too large")
    args.output.mkdir(parents=True, exist_ok=False)
    inputs = {
        str(p.resolve()): digest(p) for p in [args.engine, args.network, args.positions]
    }
    modes = {
        "classical": None,
        "mixture-exact": (10, False),
        "mixture-bounds": (10, True),
        "neural-exact": (100, False),
        "neural-bounds": (100, True),
    }
    if args.cache_comparison:
        modes = {
            "classical-exact": (0, False, False),
            "classical-cache": (0, False, True),
            "mixture-exact": (10, False, False),
            "mixture-cache": (10, False, True),
            "neural-exact": (100, False, False),
            "neural-cache": (100, False, True),
        }
    if args.combined_comparison:
        modes = {}
        for prefix, weight in [("classical", 0), ("mixture", 10), ("neural", 100)]:
            modes[prefix + "-exact"] = (weight, False, False, False)
            modes[prefix + "-combined"] = (weight, False, True, True)
    config = {
        "schema": "caissa-neural-cost-v1",
        "profile": "diagnostic",
        "inputs": inputs,
        "modes": modes,
        "nodes": args.nodes,
        "repeats": args.repeats,
        "seed": 67867979,
        "threads": 1,
        "hash_mib": 16,
        "warmup_nodes": 1,
        "maximum_seconds": 900,
        "load_note": args.load_note,
        "platform": platform.platform(),
        "full_acceptance": False,
    }
    if args.combined_comparison:
        config["exact_comparison"] = "combined"
    atomic(args.output / "CONFIG.json", config)
    start = time.monotonic()
    rng = random.Random(config["seed"])
    rows = []
    with ExitStack() as stack, (args.output / "observations.jsonl").open("x") as stream:
        clients = {}
        for mode, setting in modes.items():
            options = {"Threads": 1, "Hash": 16, "Search Stats": True}
            if setting:
                weight, bounded = setting[:2]
                if len(setting) >= 3:
                    options["Evaluation Cache"] = setting[2]
                if len(setting) == 4:
                    options["Tactical Generation"] = setting[3]
                if weight:
                    options.update(
                        {
                            "EvalFile": str(args.network.resolve()),
                            "Use Neural": True,
                            "Neural Weight": weight,
                            "Neural Bounds": bounded,
                        }
                    )
            clients[mode] = stack.enter_context(
                UciClient([str(args.engine.resolve())], options, warmup_nodes=1)
            )
        for repeat in range(args.repeats):
            for position in positions:
                order = list(modes)
                rng.shuffle(order)
                for mode in order:
                    if time.monotonic() - start >= config["maximum_seconds"]:
                        raise TimeoutError("cumulative neural cost profile deadline")
                    client = clients[mode]
                    client.send("ucinewgame")
                    client.send("isready")
                    client.until("readyok", 5)
                    move, elapsed, lines = client.play(
                        position["fen"], [], nodes=args.nodes
                    )
                    observed = info(lines)
                    replay(position["fen"], move, observed["pv"])
                    row = {
                        "repeat": repeat,
                        "position": position["id"],
                        "fen": position["fen"],
                        "mode": mode,
                        "bestmove": move,
                        "roundtrip_ms": elapsed,
                        "observed": observed,
                        "request": client.last_request,
                        "uci": lines,
                    }
                    stream.write(json.dumps(row, separators=(",", ":")) + "\n")
                    stream.flush()
                    rows.append(row)
                    atomic(
                        args.output / "PROGRESS.json",
                        {
                            "searches": len(rows),
                            "expected_searches": args.repeats
                            * len(positions)
                            * len(modes),
                            "seconds": time.monotonic() - start,
                        },
                    )
    for path, identity in inputs.items():
        if digest(Path(path)) != identity:
            raise ValueError("profile input changed during execution")
    summary = {
        "schema": "caissa-neural-cost-summary-v1",
        "status": "passed",
        "profile": "diagnostic loaded host",
        "searches": len(rows),
        "modes": {},
        "seconds": time.monotonic() - start,
        "observations_sha256": digest(args.output / "observations.jsonl"),
        "full_acceptance": False,
    }
    for mode in modes:
        subset = [r for r in rows if r["mode"] == mode]
        stats = [r["observed"]["stats"] for r in subset]
        summary["modes"][mode] = {
            "roundtrip_ms": sum(r["roundtrip_ms"] for r in subset),
            "visited_nodes": sum(s["visited_nodes"] for s in stats),
            "neural_evaluations": sum(s["neural_evaluations"] for s in stats),
            "certified_cutoffs": sum(s["neural_bound_cutoffs"] for s in stats),
            "evaluator_ns": sum(s["eval_ns"] for s in stats),
            "evaluation_cache_hits": sum(
                s.get("evaluation_cache_hits", 0) for s in stats
            ),
            "evaluation_requests": sum(s["eval_calls"] for s in stats),
        }
    result_key = (
        "paired_" + variant + "_over_exact_roundtrip_ratio"
        if exact_comparison
        else "paired_bounds_over_exact_roundtrip_ratio"
    )
    summary[result_key] = {}
    for prefix in (
        ["classical", "mixture", "neural"]
        if exact_comparison
        else ["mixture", "neural"]
    ):
        ratios = []
        for repeat in range(args.repeats):
            for position in positions:
                pair = {
                    r["mode"]: r
                    for r in rows
                    if r["repeat"] == repeat and r["position"] == position["id"]
                }
                varied = pair[
                    prefix + ("-" + variant if exact_comparison else "-bounds")
                ]
                exact = pair[prefix + "-exact"]
                if exact_comparison:
                    if (
                        any(
                            varied["observed"].get(key) != exact["observed"].get(key)
                            for key in [
                                "depth",
                                "seldepth",
                                "nodes",
                                "score_type",
                                "score",
                                "pv",
                            ]
                        )
                        or varied["bestmove"] != exact["bestmove"]
                    ):
                        raise ValueError(
                            "exact evaluation cache changed fixed-node result"
                        )
                    for key in [
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
                    ]:
                        if (
                            varied["observed"]["stats"][key]
                            != exact["observed"]["stats"][key]
                        ):
                            raise ValueError(
                                "exact evaluation cache changed search-tree counters: "
                                + key
                            )
                ratios.append(
                    varied["roundtrip_ms"] / pair[prefix + "-exact"]["roundtrip_ms"]
                )
        summary[result_key][prefix] = {
            "median": statistics.median(ratios),
            "minimum": min(ratios),
            "maximum": max(ratios),
        }
    atomic(args.output / "SUMMARY.json", summary)
    print(json.dumps(summary))


if __name__ == "__main__":
    main()
