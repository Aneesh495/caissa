"""Recompute raw heuristic ablations and re-execute their fixed-node cases.

No producer parser, scheduler, mode builder or aggregation is imported.
"""

import argparse
import contextlib
import fcntl
import hashlib
import json
import math
import random
import re
import subprocess
import time
from pathlib import Path

import chess

from verification.acquisition import sha
from verification.evaluation_cost import parse
from verification.native_session import NativeSession
from verification.protocol import read_json

MODES = (
    "reference",
    "null",
    "lmr",
    "extensions",
    "futility",
    "see",
    "history",
    "pvs",
    "aspiration",
    "quiescence",
    "table",
)
FLAGS = (
    "Null Move",
    "LMR",
    "Extensions",
    "Futility",
    "SEE",
    "History",
    "PVS",
    "Aspiration",
    "Quiescence",
    "Use Table",
)
COUNTERS = {
    "visited_nodes",
    "table_bytes",
    "elapsed_ms",
    "qnodes",
    "tt_hits",
    "ordering_hints",
    "tt_cutoffs",
    "beta_cutoffs",
    "null_cutoffs",
    "lmr",
    "researches",
    "futility",
    "eval_calls",
    "eval_ns",
    "evaluation_cache_hits",
    "evaluation_cache_bytes",
    "neural_evaluations",
    "neural_bound_cutoffs",
    "completed_depth_nodes",
}


def require(value, reason):
    if not value:
        raise ValueError(reason)


def expected_options(mode):
    require(mode in MODES, "undeclared independent heuristic mode")
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
    result.update(dict.fromkeys(FLAGS, True))
    if mode != "reference":
        result[FLAGS[MODES.index(mode) - 1]] = False
    return result


def inspect_row(row, case):
    require(row["fen"] == case["fen"], "heuristic row position differs")
    best, observed = parse(row["uci"], case["fen"])
    require(
        best == row["bestmove"] and observed == row["observed"],
        "heuristic metadata differs from actual native response",
    )
    stats_lines = [line for line in row["uci"] if line.startswith("info string stats ")]
    require(len(stats_lines) == 1, "heuristic query must have one actual work summary")
    names = stats_lines[0].split()[3::2]
    require(
        len(set(names)) == len(names)
        and all(type(v) is int and 0 <= v < 2**63 for v in observed["stats"].values()),
        "duplicated or invalid native work counter",
    )
    stats = observed["stats"]
    require(set(stats) == COUNTERS, "native heuristic counter inventory differs")
    require(
        not observed["pv"] or observed["pv"][0] == best,
        "heuristic PV root differs from best move",
    )
    require(
        stats["completed_depth_nodes"] <= stats["visited_nodes"]
        and stats["qnodes"] <= stats["visited_nodes"]
        and stats["tt_cutoffs"] <= stats["tt_hits"],
        "inconsistent heuristic work counters",
    )
    require(
        stats["neural_evaluations"] == stats["neural_bound_cutoffs"] == 0,
        "classical heuristic study used neural inference",
    )
    require(
        0 < stats["table_bytes"] <= 16 * 1024**2,
        "heuristic hash allocation exceeds matched resources",
    )
    zero = {
        "null": ("null_cutoffs",),
        "lmr": ("lmr",),
        "futility": ("futility",),
        "quiescence": ("qnodes",),
        "table": ("tt_hits", "tt_cutoffs"),
    }
    require(
        all(stats[key] == 0 for key in zero.get(row["mode"], ())),
        "disabled heuristic still reported its work",
    )
    request = row["request"]
    command = (
        "go "
        + ("nodes" if row["budget_kind"] == "nodes" else "movetime")
        + " "
        + str(row["budget"])
    )
    require(
        request["position"] == "position fen " + case["fen"]
        and request["go"] == command,
        "actual heuristic position or budget differs",
    )
    start, end = request["started_monotonic_ns"], request["completed_monotonic_ns"]
    require(
        type(start) is int
        and type(end) is int
        and end > start > 0
        and math.isfinite(row["roundtrip_ms"])
        and abs((end - start) / 1e6 - row["roundtrip_ms"]) <= 1e-9,
        "heuristic timing differs from actual request",
    )
    if row["budget_kind"] == "nodes":
        require(
            stats["visited_nodes"] <= row["budget"],
            "native heuristic exceeded its node budget",
        )
    if observed.get("score_type") == "mate" and observed.get("score") == 1:
        board = chess.Board(case["fen"])
        board.push_uci(best)
        require(board.is_checkmate(), "heuristic reported a false mate in one")
    return observed


def defer_matches(root=Path("runs")):
    """Check live owner locks independently of the collector."""
    for name in ("full-neural-strength-v3", "full-external-strength-v3"):
        path = root / name / "OWNER.lock"
        if path.exists():
            with path.open("a") as stream:
                try:
                    fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError as error:
                    raise ValueError(
                        "decisive matches own the host; defer independent heuristic replay"
                    ) from error


def check_groups(rows, groups):
    table = {
        (r["repeat"], r["position"], r["budget_kind"], r["budget"], r["mode"]): r
        for r in rows
    }
    identifiers = sorted({r["position"] for r in rows})
    expected_names = set()
    for mode in MODES:
        for kind, budgets in [("nodes", [5000, 25000]), ("milliseconds", [25, 100])]:
            for budget in budgets:
                label = f"{mode}:{kind}:{budget}"
                expected_names.add(label)
                pairs = [
                    (
                        table[repeat, case, kind, budget, mode],
                        table[repeat, case, kind, budget, "reference"],
                    )
                    for repeat in range(3)
                    for case in identifiers
                ]
                saved = groups[label]
                sample = [a for a, _ in pairs]
                require(saved["queries"] == 24, "heuristic summary sample differs")
                values = sorted(a["roundtrip_ms"] / b["roundtrip_ms"] for a, b in pairs)
                median = (values[11] + values[12]) / 2
                require(
                    abs(saved["median_roundtrip_over_reference"] - median) < 1e-12,
                    "heuristic paired timing summary differs",
                )
                expected = {
                    "mean_completed_depth": sum(
                        a["observed"].get("depth", 0) for a in sample
                    )
                    / 24,
                    "zero_completed_depth": sum(
                        a["observed"].get("depth", 0) == 0 for a in sample
                    ),
                    "changed_bestmoves": sum(
                        a["bestmove"] != b["bestmove"] for a, b in pairs
                    ),
                    "visited_nodes": sum(
                        a["observed"]["stats"]["visited_nodes"] for a in sample
                    ),
                    "completed_depth_nodes": sum(
                        a["observed"]["stats"]["completed_depth_nodes"] for a in sample
                    ),
                }
                require(
                    all(
                        abs(saved[key] - value) <= 1e-12
                        for key, value in expected.items()
                    ),
                    "heuristic work, depth or decision summary differs",
                )
                counters = {
                    key: sum(a["observed"]["stats"][key] for a in sample)
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
                }
                require(
                    saved["work_counters"] == counters,
                    "heuristic counter aggregate differs",
                )
    require(set(groups) == expected_names, "heuristic group inventory differs")


def verify(args):
    started, deadline = time.time(), time.time() + args.maximum_seconds
    require(
        0 < args.maximum_seconds <= 900,
        "finite heuristic verification ceiling required",
    )
    defer_matches()
    require(
        sha(args.protocol) == args.expected_protocol_sha256
        and sha(args.engine) == args.expected_engine_sha256,
        "heuristic external input identity differs",
    )
    rule = read_json(args.protocol.read_text())
    required = {
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
    require(
        all(
            type(rule.get(k)) is type(value) and rule.get(k) == value
            for k, value in required.items()
        ),
        "heuristic frozen sample or control contract differs",
    )
    positions = Path(rule["positions"])
    require(
        sha(positions) == rule["positions_sha256"],
        "heuristic frozen position bytes differ",
    )
    cases = read_json(positions.read_text())["positions"]
    require(
        len(cases) == 8 and len({p["id"] for p in cases}) == 8,
        "heuristic position inventory differs",
    )
    config = read_json((args.evidence / "CONFIG.json").read_text())
    summary = read_json((args.evidence / "SUMMARY.json").read_text())
    require(
        summary["status"] == "completed fixed heuristic query matrix"
        and 0 < summary["seconds"] <= 600,
        "heuristic study completion or ceiling differs",
    )
    require(
        config["protocol"] == rule
        and config["modes"] == {m: expected_options(m) for m in MODES},
        "heuristic control was weakened or unrelated options changed",
    )
    require(
        config["inputs"]["engine"] == args.expected_engine_sha256
        and config["inputs"]["protocol"] == args.expected_protocol_sha256
        and config["inputs"]["positions"] == sha(positions),
        "heuristic saved input identity differs",
    )
    commit = config["collector_source_commit"]
    require(
        re.fullmatch("[0-9a-f]{40}", commit) is not None,
        "heuristic collector source identity is malformed",
    )
    source = subprocess.check_output(
        ["git", "show", commit + ":tools/heuristic_study.py"], timeout=5
    )
    require(
        len(source) <= 1024**2
        and hashlib.sha256(source).hexdigest() == config["inputs"]["collector"],
        "heuristic collector differs from committed source",
    )
    sessions = read_json((args.evidence / "SESSIONS.json").read_text())
    require(
        set(sessions) == set(MODES)
        and len({s["pid"] for s in sessions.values()}) == len(MODES),
        "heuristic actual session inventory differs",
    )
    for mode, session in sessions.items():
        commands = [
            "setoption name "
            + key
            + " value "
            + (str(value).lower() if type(value) is bool else str(value))
            for key, value in expected_options(mode).items()
        ]
        require(
            session["configuration_commands"] == commands
            and session["warmup_nodes"] == 1
            and session["warmup_ms"] > 0,
            "actual heuristic session options or warmup differ",
        )
        require(
            session["handshake"][-1] == "uciok",
            "heuristic actual UCI handshake is incomplete",
        )
    raw = args.evidence / "observations.jsonl"
    require(
        0 < raw.stat().st_size <= 134217728
        and sha(raw) == summary["observations_sha256"],
        "heuristic observation size or hash differs",
    )
    rows = [read_json(line) for line in raw.read_text().splitlines()]
    schedule = [
        (repeat, case["id"], kind, budget, mode)
        for repeat in range(3)
        for case in cases
        for kind in ("nodes", "milliseconds")
        for budget in rule[kind]
        for mode in MODES
    ]
    random.Random(32452843).shuffle(schedule)
    require(
        len(rows) == summary["queries"] == 1056, "heuristic fixed sample is incomplete"
    )
    require(
        [
            (r["repeat"], r["position"], r["budget_kind"], r["budget"], r["mode"])
            for r in rows
        ]
        == schedule,
        "heuristic actual schedule differs or duplicated a query",
    )
    by_id = {case["id"]: case for case in cases}
    previous = 0
    for row in rows:
        require(time.time() < deadline, "heuristic verification deadline exhausted")
        inspect_row(row, by_id[row["position"]])
        require(
            row["request"]["started_monotonic_ns"] > previous,
            "heuristic requests overlap or their order differs",
        )
        previous = row["request"]["completed_monotonic_ns"]
    check_groups(rows, summary["groups"])
    require(
        summary["absolute_elo"] is None
        and summary["full_acceptance"] is False
        and config["absolute_elo"] is None
        and config["full_acceptance"] is False,
        "diagnostic heuristic queries cannot claim strength or release",
    )
    require(
        not args.output.resolve().is_relative_to(args.evidence.resolve()),
        "independent heuristic replay must preserve original evidence",
    )
    args.output.mkdir(parents=True, exist_ok=False)
    replayed = 0
    with (
        contextlib.ExitStack() as stack,
        (args.output / "fixed-node-replay.jsonl").open("x") as stream,
    ):
        clients = {
            mode: stack.enter_context(
                contextlib.closing(
                    NativeSession(args.engine, expected_options(mode), deadline)
                )
            )
            for mode in MODES
        }
        for row in rows:
            if row["budget_kind"] != "nodes":
                continue
            defer_matches()
            session = clients[row["mode"]]
            lines = session.search(row["fen"], row["budget"])
            best, observed = parse(lines, row["fen"])
            stable = lambda value: {
                k: v
                for k, v in value.items()
                if k not in ("time", "nps", "hashfull", "stats")
            }
            work = lambda value: {
                k: v
                for k, v in value["stats"].items()
                if k not in ("elapsed_ms", "eval_ns")
            }
            require(
                best == row["bestmove"]
                and stable(observed) == stable(row["observed"])
                and work(observed) == work(row["observed"]),
                "independent heuristic fixed-node replay differs",
            )
            stream.write(
                json.dumps(
                    {
                        "key": [
                            row[k] for k in ("repeat", "position", "mode", "budget")
                        ],
                        "uci": lines,
                    },
                    separators=(",", ":"),
                )
                + "\n"
            )
            replayed += 1
    require(
        replayed == 528 and sha(raw) == summary["observations_sha256"],
        "heuristic replay sample or original bytes changed",
    )
    require(
        sha(args.engine) == args.expected_engine_sha256
        and sha(args.protocol) == args.expected_protocol_sha256,
        "heuristic replay external inputs changed",
    )
    result = {
        "status": "passed",
        "raw_queries_recomputed": 1056,
        "fixed_node_queries_independently_reexecuted": replayed,
        "seconds": time.time() - started,
        "absolute_elo": None,
        "full_acceptance": False,
        "scope": "Frozen loaded-host heuristic ablations. Timed searches remain actual observations, not deterministic replay targets or measured playing strength.",
    }
    (args.output / "SUMMARY.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("evidence", type=Path)
    parser.add_argument("--engine", type=Path, required=True)
    parser.add_argument("--expected-engine-sha256", required=True)
    parser.add_argument("--protocol", type=Path, required=True)
    parser.add_argument("--expected-protocol-sha256", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--maximum-seconds", type=float, default=300)
    verify(parser.parse_args())


if __name__ == "__main__":
    main()
