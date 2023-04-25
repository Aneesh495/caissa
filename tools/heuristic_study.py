"""Frozen, paired switch-off studies of original search heuristics.

Every query keeps the same original classical evaluator and unrelated options.
Node/time experiments describe work and decisions, never an inferred Elo gain.
"""

import argparse
import fcntl
import json
import os
import random
import statistics
import subprocess
import time
from contextlib import ExitStack
from pathlib import Path

from arena.client import UciClient
from tools.campaign_process import atomic
from tools.performance import info, replay
from verification.acquisition import sha
from verification.protocol import read_json

SWITCHES = {
    "null": "Null Move",
    "lmr": "LMR",
    "extensions": "Extensions",
    "futility": "Futility",
    "see": "SEE",
    "history": "History",
    "pvs": "PVS",
    "aspiration": "Aspiration",
    "quiescence": "Quiescence",
    "table": "Use Table",
}


def contract(path, expected):
    if sha(path) != expected:
        raise ValueError("heuristic protocol differs from its external identity")
    rule = read_json(path.read_text())
    exact = {
        "schema": "caissa-heuristic-study-v1",
        "status": "frozen",
        "profile": "diagnostic-loaded-host",
        "positions": "config/performance.json",
        "positions_sha256": "8a27cea07ff367e7c991a5c855a1d4620a7f43b8578f95309e8d50f0ad63fcfe",
        "nodes": [5000, 25000],
        "milliseconds": [25, 100],
        "repeats": 3,
        "schedule_seed": 32452843,
        "threads": 1,
        "hash_mib": 16,
        "warmup_nodes": 1,
        "maximum_seconds": 600,
        "maximum_observation_bytes": 134217728,
    }
    if any(
        type(rule.get(key)) is not type(value) or rule.get(key) != value
        for key, value in exact.items()
    ):
        raise ValueError("heuristic sample, reference resources or ceiling differs")
    positions = Path(rule["positions"])
    if sha(positions) != rule["positions_sha256"]:
        raise ValueError("frozen heuristic position bytes differ")
    cases = read_json(positions.read_text())["positions"]
    if len(cases) != 8 or len({p["id"] for p in cases}) != len(cases):
        raise ValueError("heuristic case inventory differs")
    return rule, cases


def options(mode):
    result = {
        "Threads": 1,
        "Hash": 16,
        "MultiPV": 1,
        "Search Stats": True,
        "Trace Samples": 0,
        "Use Neural": False,
        "Evaluation Cache": True,
        "Tactical Generation": True,
        "Ordering Hints": False,
        "Neural Bounds": False,
    }
    result.update({name: True for name in SWITCHES.values()})
    if mode != "reference":
        if mode not in SWITCHES:
            raise ValueError("undeclared heuristic mode")
        result[SWITCHES[mode]] = False
    return result


def avoid_decisive_matches(root=Path("runs")):
    paths = [
        root / name / "OWNER.lock"
        for name in (
            "full-neural-strength-v3",
            "full-external-strength-v3",
            "full-neural-strength-v4",
            "full-external-strength-v4",
        )
    ]
    paths.append(root / "TIMED_STRENGTH.lock")
    for path in paths:
        if path.exists():
            if path.name == "TIMED_STRENGTH.lock":
                from tools.host_lease import inherited

                if inherited(path):
                    continue
            with path.open("a") as stream:
                try:
                    fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError as error:
                    raise ValueError(
                        "timed decisive matches own the host; defer the heuristic study"
                    ) from error


def summarize(rows):
    grouped = {}
    for row in rows:
        key = (row["repeat"], row["position"], row["budget_kind"], row["budget"])
        if row["mode"] in grouped.setdefault(key, {}):
            raise ValueError("duplicated heuristic query identity")
        grouped[key][row["mode"]] = row
    result = {}
    for mode in ("reference", *SWITCHES):
        for kind in ("nodes", "milliseconds"):
            for budget in sorted(
                {r["budget"] for r in rows if r["budget_kind"] == kind}
            ):
                pairs = [
                    value for key, value in grouped.items() if key[2:] == (kind, budget)
                ]
                if any(set(p) != {"reference", *SWITCHES} for p in pairs):
                    raise ValueError("incomplete heuristic query matrix")
                subset, base = [p[mode] for p in pairs], [p["reference"] for p in pairs]
                elapsed = [
                    a["roundtrip_ms"] / b["roundtrip_ms"] for a, b in zip(subset, base)
                ]
                result[f"{mode}:{kind}:{budget}"] = {
                    "queries": len(subset),
                    "median_roundtrip_over_reference": statistics.median(elapsed),
                    "mean_completed_depth": statistics.mean(
                        r["observed"].get("depth", 0) for r in subset
                    ),
                    "zero_completed_depth": sum(
                        r["observed"].get("depth", 0) == 0 for r in subset
                    ),
                    "changed_bestmoves": sum(
                        a["bestmove"] != b["bestmove"] for a, b in zip(subset, base)
                    ),
                    "visited_nodes": sum(
                        r["observed"]["stats"]["visited_nodes"] for r in subset
                    ),
                    "completed_depth_nodes": sum(
                        r["observed"]["stats"]["completed_depth_nodes"] for r in subset
                    ),
                    "work_counters": {
                        key: sum(r["observed"]["stats"][key] for r in subset)
                        for key in (
                            "qnodes",
                            "tt_hits",
                            "tt_cutoffs",
                            "beta_cutoffs",
                            "null_cutoffs",
                            "lmr",
                            "researches",
                            "futility",
                            "eval_calls",
                        )
                    },
                }
    return result


def execute(args):
    rule, cases = contract(args.protocol, args.expected_protocol_sha256)
    if sha(args.engine) != args.expected_engine_sha256:
        raise ValueError("heuristic engine differs from its external frozen identity")
    avoid_decisive_matches()
    args.output.mkdir(parents=True, exist_ok=False)
    started, wall = time.monotonic(), time.time()
    paths = {
        "engine": args.engine,
        "protocol": args.protocol,
        "positions": Path(rule["positions"]),
        "collector": Path(__file__),
    }
    identities = {name: sha(path) for name, path in paths.items()}
    modes = ("reference", *SWITCHES)
    atomic(
        args.output / "CONFIG.json",
        {
            "schema": "caissa-heuristic-observations-v1",
            "protocol": rule,
            "inputs": identities,
            "modes": {m: options(m) for m in modes},
            "collector_source_commit": subprocess.check_output(
                ["git", "rev-parse", "HEAD"], text=True, timeout=5
            ).strip(),
            "host_load_note": args.load_note,
            "load_start": list(os.getloadavg()),
            "absolute_elo": None,
            "full_acceptance": False,
        },
    )
    schedule = [
        (repeat, case, kind, budget, mode)
        for repeat in range(rule["repeats"])
        for case in cases
        for kind in ("nodes", "milliseconds")
        for budget in rule[kind]
        for mode in modes
    ]
    random.Random(rule["schedule_seed"]).shuffle(schedule)
    rows, byte_count = [], 0
    with ExitStack() as stack, (args.output / "observations.jsonl").open("x") as stream:
        clients = {
            mode: stack.enter_context(
                UciClient([str(args.engine.resolve())], options(mode), warmup_nodes=1)
            )
            for mode in modes
        }
        atomic(
            args.output / "SESSIONS.json",
            {
                mode: {
                    "pid": client.process.pid,
                    "handshake": client.handshake,
                    "configuration_commands": client.configuration_commands,
                    "warmup_nodes": 1,
                    "warmup_ms": client.warmup_ms,
                }
                for mode, client in clients.items()
            },
        )
        for repeat, case, kind, budget, mode in schedule:
            if (
                time.monotonic() - started >= rule["maximum_seconds"]
                or time.time() - wall >= rule["maximum_seconds"]
            ):
                raise TimeoutError("heuristic study cumulative deadline exhausted")
            avoid_decisive_matches()
            client = clients[mode]
            client.send("ucinewgame")
            client.send("isready")
            client.until("readyok", 5)
            best, elapsed, lines = client.play(case["fen"], [], **{kind: budget})
            observed = info(lines)
            replay(case["fen"], best, observed["pv"])
            row = {
                "repeat": repeat,
                "position": case["id"],
                "fen": case["fen"],
                "mode": mode,
                "budget_kind": kind,
                "budget": budget,
                "bestmove": best,
                "roundtrip_ms": elapsed,
                "observed": observed,
                "request": client.last_request,
                "uci": lines,
            }
            raw = json.dumps(row, separators=(",", ":")) + "\n"
            byte_count += len(raw.encode())
            if byte_count > rule["maximum_observation_bytes"]:
                raise ValueError("heuristic observation byte ceiling exhausted")
            stream.write(raw)
            stream.flush()
            rows.append(row)
            atomic(
                args.output / "PROGRESS.json",
                {
                    "queries": len(rows),
                    "expected": len(schedule),
                    "seconds": time.monotonic() - started,
                },
            )
    if identities != {name: sha(path) for name, path in paths.items()}:
        raise ValueError("heuristic experiment inputs changed")
    if (
        time.monotonic() - started >= rule["maximum_seconds"]
        or time.time() - wall >= rule["maximum_seconds"]
    ):
        raise TimeoutError("heuristic study finalization exceeded its original ceiling")
    result = {
        "status": "completed fixed heuristic query matrix",
        "queries": len(rows),
        "observations_sha256": sha(args.output / "observations.jsonl"),
        "groups": summarize(rows),
        "seconds": time.monotonic() - started,
        "absolute_elo": None,
        "full_acceptance": False,
        "scope": "Loaded-host diagnostic of work/depth/root decisions; no heuristic strength or isolated-speed conclusion, model selection or baseline tuning",
    }
    atomic(args.output / "SUMMARY.json", result)
    print(
        json.dumps(
            {
                key: result[key]
                for key in ("status", "queries", "seconds", "full_acceptance")
            }
        )
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--engine", type=Path, required=True)
    parser.add_argument("--expected-engine-sha256", required=True)
    parser.add_argument("--protocol", type=Path, required=True)
    parser.add_argument("--expected-protocol-sha256", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--load-note", required=True)
    execute(parser.parse_args())


if __name__ == "__main__":
    main()
