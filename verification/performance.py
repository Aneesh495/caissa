"""Independent raw performance, RSS and latency reconstruction.

Recomputes measured aggregates and reruns the frozen scalar/native node probes.
Timed search counts and RSS are observations, not deterministic replay targets.
No producer parser, statistics function or transport is imported.
"""

import argparse
import collections
import contextlib
import json
import math
import time
from pathlib import Path

import chess

from verification.acquisition import sha
from verification.evaluation_cost import parse
from verification.native_session import NativeSession
from verification.protocol import read_json

EVALUATIONS = ("classical", "neural-native", "neural-scalar", "neural-blend")


def require(condition, reason):
    if not condition:
        raise ValueError(reason)


def document(path, maximum=4 * 1024 * 1024):
    require(
        not path.is_symlink() and 0 < path.stat().st_size <= maximum,
        "performance document exceeds bounded replay or uses a symlink",
    )
    return read_json(path.read_text())


def records(path, maximum_bytes, maximum_rows):
    require(
        not path.is_symlink() and 0 < path.stat().st_size <= maximum_bytes,
        "performance records exceed bounded replay or use a symlink",
    )
    with path.open() as stream:
        for index, line in enumerate(stream):
            require(
                index < maximum_rows and len(line) <= 1024 * 1024,
                "performance record count or line ceiling",
            )
            yield read_json(line)


def percentiles(values):
    ordered = sorted(values)
    require(bool(ordered), "empty performance metric")
    result = {}
    for name, q in [("p50", 0.5), ("p95", 0.95), ("p99", 0.99)]:
        at = (len(ordered) - 1) * q
        lo = int(at)
        fraction = at - lo
        result[name] = ordered[lo] + fraction * (
            ordered[min(lo + 1, len(ordered) - 1)] - ordered[lo]
        )
    return {**result, "max": ordered[-1], "count": len(ordered)}


def equal(actual, expected, label):
    if isinstance(expected, dict):
        require(
            isinstance(actual, dict) and actual.keys() == expected.keys(),
            "performance summary field inventory differs: " + label,
        )
        for key in expected:
            equal(actual[key], expected[key], label + "." + key)
    elif isinstance(expected, list):
        require(
            isinstance(actual, list) and len(actual) == len(expected),
            "performance summary list differs: " + label,
        )
        for i, (left, right) in enumerate(zip(actual, expected)):
            equal(left, right, label + "." + str(i))
    elif isinstance(expected, float):
        require(
            type(actual) in (int, float)
            and math.isfinite(actual)
            and math.isclose(actual, expected, rel_tol=1e-10, abs_tol=1e-8),
            "independent performance metric differs: " + label,
        )
    else:
        require(
            type(actual) is type(expected) and actual == expected,
            "performance summary value differs: " + label,
        )


def metrics(rows):
    duration = sum(row["roundtrip_ms"] for row in rows) / 1000
    stat = [row["observed"]["stats"] for row in rows]
    visited = sum(row["visited_nodes"] for row in stat)
    useful = sum(row["completed_depth_nodes"] for row in stat)
    calls = sum(row["eval_calls"] for row in stat)
    return {
        "searches": len(rows),
        "roundtrip_ms": percentiles([row["roundtrip_ms"] for row in rows]),
        "mean_depth": sum(row["observed"].get("depth", 0) for row in rows) / len(rows),
        "mean_visited_nodes": visited / len(rows),
        "mean_useful_nodes": useful / len(rows),
        "visited_nodes_per_second": visited / duration,
        "useful_nodes_per_second": useful / duration,
        "evaluator_ns_per_call": (
            sum(row["eval_ns"] for row in stat) / calls if calls else None
        ),
        "table_bytes": sorted({row["table_bytes"] for row in stat}),
        "evaluation_cache_bytes": sorted(
            {row["evaluation_cache_bytes"] for row in stat}
        ),
    }


def options(evaluation, threads, config, model_path, optimized):
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
        require(
            type(model_path) is str and 0 < len(model_path) <= 4096,
            "performance model path is missing",
        )
        result.update(
            {
                "EvalFile": model_path,
                "Use Neural": True,
                "Scalar Neural": evaluation == "neural-scalar",
                "Neural Weight": 10 if evaluation == "neural-blend" else 100,
            }
        )
    return result


def request(row, fen, command, previous):
    event = row["request"]
    start, end = event["started_monotonic_ns"], event["completed_monotonic_ns"]
    require(
        type(start) is int and type(end) is int and 0 <= previous <= start < end,
        "performance request timestamps are inconsistent",
    )
    require(
        event["go"] == command and event["position"] == "position fen " + fen,
        "performance actual request changes the frozen resource or position",
    )
    duration = (end - start) / 1e6
    require(
        type(row["roundtrip_ms"]) in (float, int)
        and abs(row["roundtrip_ms"] - duration) < 1e-9,
        "performance request duration differs from actual timestamps",
    )
    return end


def verify(
    root,
    engine,
    network,
    positions,
    expected_config,
    maximum_seconds=600,
    full=False,
    replay_output=None,
):
    require(
        1 <= maximum_seconds <= 1800, "finite independent performance ceiling required"
    )
    started = time.time()
    deadline = started + maximum_seconds

    def budget():
        require(
            time.time() < deadline,
            "independent performance verification deadline exhausted",
        )

    config = document(root / "CONFIG.json")
    summary = document(root / "SUMMARY.json")
    frozen = document(positions)
    require(
        config["schema"] == "caissa-performance-run-v2"
        and summary["schema"] == "caissa-performance-summary-v2",
        "performance evidence lacks raw v2 measurements",
    )
    require(
        config["engine_sha256"] == sha(engine)
        and config["network_sha256"] == sha(network),
        "performance executable or selected network identity differs",
    )
    require(
        config["config_sha256"] == expected_config == sha(positions)
        and config["config"] == frozen,
        "performance workload differs from external frozen identity",
    )
    require(
        type(config["exact_optimizations"]) is bool,
        "performance optimization flag is not boolean",
    )
    require(
        config["deadline_unix"] == config["started_unix"] + config["maximum_seconds"]
        and 1 <= config["maximum_seconds"] <= 3600
        and 0 <= summary["wall_seconds"] <= config["maximum_seconds"],
        "performance cumulative resource deadline differs",
    )
    if full:
        require(
            config["profile"] == "full-performance-unverified"
            and config["exact_optimizations"] is True,
            "full performance cannot use a diagnostic or different optimization contract",
        )
        require(
            frozen["threads"] == [1, 2, 4, 8]
            and frozen["milliseconds"] == 250
            and frozen["repeats"] >= 5
            and frozen["latency_samples"] >= 1000
            and len(frozen["positions"]) >= 8
            and config["cpu_count"] >= 8,
            "full performance workload or supported host is incomplete",
        )
    threads = frozen["threads"]
    positions_by_id = {row["id"]: row for row in frozen["positions"]}
    require(
        threads
        and len(set(threads)) == len(threads)
        and all(type(t) is int and t in (1, 2, 4, 8) for t in threads),
        "invalid performance thread inventory",
    )
    require(
        1 <= frozen["repeats"] <= 20
        and 1 <= frozen["latency_samples"] <= 10000
        and 1 <= len(positions_by_id) == len(frozen["positions"]) <= 100
        and 1 <= frozen["hash_mib"] <= 1024
        and 20 <= frozen["milliseconds"] <= 10000,
        "performance workload exceeds finite bounds",
    )
    names = {
        "measurements.jsonl",
        "memory.jsonl",
        "latency.jsonl",
        "correctness.json",
        "SESSIONS.json",
    }
    require(set(summary["files"]) == names, "performance artifact inventory differs")
    for name in names:
        budget()
        limit = (
            128 * 1024 * 1024
            if name == "measurements.jsonl"
            else (
                32 * 1024 * 1024
                if name in ("memory.jsonl", "latency.jsonl")
                else 4 * 1024 * 1024
            )
        )
        require(
            not (root / name).is_symlink()
            and 0 < (root / name).stat().st_size <= limit,
            "performance artifact size exceeds bounded replay before hashing",
        )
        require(
            sha(root / name) == summary["files"][name],
            "performance artifact corruption: " + name,
        )
    sessions = document(root / "SESSIONS.json")
    require(
        len(sessions) == 4 * len(threads) + 2 * len(positions_by_id) + 2,
        "performance native session inventory differs",
    )
    for index, session in enumerate(sessions):
        require(
            session["id"] == index
            and type(session["pid"]) is int
            and session["pid"] > 0
            and session["evaluation"] in EVALUATIONS,
            "performance native session identity differs",
        )
        actual = session["options"]
        expected = options(
            session["evaluation"],
            session["threads"],
            frozen,
            actual.get("EvalFile"),
            config["exact_optimizations"],
        )
        require(
            actual == expected, "performance actual evaluator/resource options differ"
        )
        declarations = {
            line[12:].split(" type ", 1)[0]
            for line in session["handshake"]
            if line.startswith("option name ") and " type " in line
        }
        require(
            session["handshake"][-1] == "uciok" and set(actual) <= declarations,
            "performance options were not declared by native preflight",
        )
        commands = [
            "setoption name "
            + name
            + " value "
            + (str(value).lower() if type(value) is bool else str(value))
            for name, value in actual.items()
        ]
        require(
            commands == session["configuration_commands"],
            "performance actual configuration command sequence differs",
        )
    rows = list(records(root / "measurements.jsonl", 128 * 1024 * 1024, 320000))
    expected = {
        (evaluation, t, repeat, position)
        for evaluation in EVALUATIONS
        for t in threads
        for repeat in range(frozen["repeats"])
        for position in positions_by_id
    }
    require(len(rows) == len(expected), "performance timed search sample is incomplete")
    previous = 0
    for row in rows:
        budget()
        key = (row["evaluation"], row["threads"], row["repeat"], row["position"])
        require(key in expected, "duplicate or unfrozen performance search")
        expected.remove(key)
        require(
            row["fen"] == positions_by_id[row["position"]]["fen"],
            "performance input position differs",
        )
        session = sessions[row["session"]]
        require(
            session["evaluation"] == row["evaluation"]
            and session["threads"] == row["threads"]
            and 0 <= row["session"] < 4 * len(threads),
            "timed profile changed native session",
        )
        previous = request(
            row, row["fen"], "go movetime " + str(frozen["milliseconds"]), previous
        )
        move, observed = parse(row["uci"], row["fen"])
        require(
            move == row["bestmove"] and observed == row["observed"],
            "performance parsed result differs from actual native output",
        )
        stat = observed["stats"]
        require(
            stat["neural_bound_cutoffs"] == 0 and stat["ordering_hints"] == 0,
            "performance used disabled search options",
        )
        if row["evaluation"] == "classical":
            require(
                stat["neural_evaluations"] == 0,
                "classical resource profile ran a neural evaluator",
            )
        else:
            require(
                stat["eval_calls"]
                == stat["neural_evaluations"] + stat["evaluation_cache_hits"]
                and (stat["eval_calls"] == 0 or stat["neural_evaluations"] > 0),
                "neural resource profile lacks actual inference or correct cache accounting",
            )
        require(
            all(type(v) is int and v >= 0 for v in stat.values())
            and 0 < stat["table_bytes"] <= frozen["hash_mib"] * 1024**2
            and stat["completed_depth_nodes"] <= stat["visited_nodes"],
            "performance native memory or node accounting is invalid",
        )
        require(
            stat["evaluation_cache_bytes"]
            == (524288 * row["threads"] if config["exact_optimizations"] else 0),
            "performance private cache allocation differs",
        )
        require(
            session["started_ns"]
            <= row["request"]["started_monotonic_ns"]
            <= row["request"]["completed_monotonic_ns"]
            <= session["completed_ns"],
            "performance request is outside its actual native session",
        )
    memory = collections.defaultdict(list)
    last_stamp = collections.defaultdict(int)
    for row in records(root / "memory.jsonl", 32 * 1024 * 1024, 200000):
        budget()
        sid = row["session"]
        require(
            type(sid) is int and 0 <= sid < 4 * len(threads),
            "RSS sample references a non-profile process",
        )
        session = sessions[sid]
        require(
            type(row["pid"]) is int
            and type(row["started_ns"]) is int
            and type(row["completed_ns"]) is int,
            "RSS identity and timestamps must be integers",
        )
        require(
            row["pid"] == session["pid"]
            and row["evaluation"] == session["evaluation"]
            and row["threads"] == session["threads"],
            "RSS sample process or profile differs",
        )
        require(
            session["started_ns"] <= last_stamp[sid] or last_stamp[sid] == 0,
            "RSS ordering state differs",
        )
        require(
            max(last_stamp[sid], session["started_ns"])
            <= row["started_ns"]
            <= row["completed_ns"]
            <= session["completed_ns"],
            "RSS timestamps are inconsistent or outside native lifetime",
        )
        last_stamp[sid] = row["completed_ns"]
        require(
            len(row["ps_stdout"]) + len(row["ps_stderr"]) <= 4096,
            "RSS response byte ceiling",
        )
        if row["ps_exit"] == 0 and row["ps_stdout"].strip():
            measured = int(row["ps_stdout"].strip()) * 1024
            require(
                type(row["rss_bytes"]) is int and row["rss_bytes"] == measured > 0,
                "RSS bytes differ from actual ps observation",
            )
            memory[sid].append(measured)
        else:
            require(row["rss_bytes"] is None, "failed RSS query invented a measurement")
    calculated = []
    for evaluation in EVALUATIONS:
        for t in threads:
            subset = [
                row
                for row in rows
                if row["evaluation"] == evaluation and row["threads"] == t
            ]
            sid = subset[0]["session"]
            require(memory[sid], "profile has no actual RSS samples")
            calculated.append(
                {
                    "evaluation": evaluation,
                    "threads": t,
                    **metrics(subset),
                    "maximum_resident_bytes": max(memory[sid]),
                    "rss_samples": len(memory[sid]),
                    "per_position": [
                        {
                            "position": position,
                            **metrics(
                                [row for row in subset if row["position"] == position]
                            ),
                        }
                        for position in positions_by_id
                    ],
                }
            )
    equal(summary["profiles"], calculated, "profiles")
    latency = collections.defaultdict(list)
    stop = []
    seen = set()
    last = previous
    for row in records(root / "latency.jsonl", 32 * 1024 * 1024, 20001):
        budget()
        start, end = row["started_ns"], row["completed_ns"]
        require(
            type(start) is int and type(end) is int and last <= start < end,
            "latency timestamps are inconsistent",
        )
        last = end
        require(
            abs(row["roundtrip_ms"] - (end - start) / 1e6) < 1e-9,
            "latency differs from raw request timestamps",
        )
        session = sessions[row["session"]]
        require(
            session["evaluation"] == "classical" and session["threads"] == max(threads),
            "latency request changed frozen resource session",
        )
        require(
            row["session"] == len(sessions) - (1 if row["active"] else 2),
            "latency active/idle session identity differs",
        )
        require(
            row["reply"]
            and not any(line.startswith("info string error ") for line in row["reply"]),
            "latency request was rejected or unfinished",
        )
        for line in row["reply"]:
            if line.startswith("info depth ") and " pv " in line:
                board = chess.Board()
                for text in line.split(" pv ", 1)[1].split():
                    move = chess.Move.from_uci(text)
                    require(
                        move in board.legal_moves,
                        "latency transcript contains an illegal PV",
                    )
                    board.push(move)
        if row["command"] == "isready":
            key = (row["active"], row["index"])
            require(
                type(row["active"]) is bool
                and key not in seen
                and 0 <= row["index"] < frozen["latency_samples"]
                and row["reply"][-1] == "readyok",
                "readiness latency sample is duplicate or incomplete",
            )
            seen.add(key)
            latency[row["active"]].append(row["roundtrip_ms"])
        else:
            require(
                row["command"] == "stop"
                and row["active"] is True
                and row["reply"][-1].startswith("bestmove "),
                "invalid stop latency record",
            )
            move = chess.Move.from_uci(row["reply"][-1].split()[1])
            require(
                move in chess.Board().legal_moves,
                "latency stop returned an illegal fallback",
            )
            stop.append(row["roundtrip_ms"])
    require(
        len(seen) == 2 * frozen["latency_samples"] and len(stop) == 1,
        "performance latency sample is incomplete",
    )
    equal(
        summary["latency"],
        {
            "idle": percentiles(latency[False]),
            "active": percentiles(latency[True]),
            "stop_ms": stop[0],
        },
        "latency",
    )
    correctness = document(root / "correctness.json")
    require(
        len(correctness)
        == len(positions_by_id)
        == summary["fixed_node_parity_positions"],
        "performance scalar correctness sample is incomplete",
    )
    logical = ["depth", "seldepth", "nodes", "score_type", "score", "pv"]
    replayed = 0
    if replay_output:
        require(
            not replay_output.resolve().is_relative_to(root.resolve()),
            "independent performance output must be outside immutable measured evidence",
        )
    with contextlib.ExitStack() as stack:
        replay_log = (
            stack.enter_context(replay_output.open("x")) if replay_output else None
        )
        clients = {}
        for evaluation in ["neural-native", "neural-scalar"]:
            selected = options(
                evaluation,
                1,
                frozen,
                str(network.resolve()),
                config["exact_optimizations"],
            )
            clients[evaluation] = stack.enter_context(
                NativeSession(engine, selected, deadline)
            )
        for row, position in zip(correctness, frozen["positions"]):
            budget()
            require(
                row["fen"] == position["fen"]
                and row["position"] == position["id"]
                and row["node_budget"] == 10000
                and len(row["cases"]) == 2,
                "performance scalar correctness workload differs",
            )
            pair = []
            for scalar, case in enumerate(row["cases"]):
                require(
                    case["scalar"] is bool(scalar),
                    "scalar/native correctness labels were swapped",
                )
                request(
                    {
                        **case,
                        "roundtrip_ms": (
                            case["request"]["completed_monotonic_ns"]
                            - case["request"]["started_monotonic_ns"]
                        )
                        / 1e6,
                    },
                    row["fen"],
                    "go nodes 10000",
                    0,
                )
                move, observed = parse(case["uci"], row["fen"])
                semantic = {key: observed.get(key) for key in logical}
                require(
                    case["bestmove"] == move and case["semantic"] == semantic,
                    "scalar correctness fields differ from native output",
                )
                evaluation = "neural-scalar" if scalar else "neural-native"
                actual = clients[evaluation].search(row["fen"], 10000)
                new_move, new_observed = parse(actual, row["fen"])
                require(
                    new_move == move
                    and {key: new_observed.get(key) for key in logical} == semantic,
                    "independent scalar/native fixed-node replay differs",
                )
                pair.append((move, semantic))
                replayed += 1
                if replay_log:
                    replay_log.write(
                        json.dumps(
                            {
                                "position": row["position"],
                                "scalar": bool(scalar),
                                "actual_uci": actual,
                            }
                        )
                        + "\n"
                    )
            require(
                pair[0] == pair[1], "performance scalar/native correctness is not exact"
            )
    require(
        sha(engine) == config["engine_sha256"]
        and sha(network) == config["network_sha256"]
        and sha(positions) == expected_config,
        "performance trusted inputs changed during replay",
    )
    return {
        "status": "passed",
        "scope": (
            "full performance workload replay"
            if full
            else "independent diagnostic performance replay"
        ),
        "timed_searches": len(rows),
        "independent_fixed_node_searches": replayed,
        "rss_samples": sum(map(len, memory.values())),
        "latency_samples": len(seen),
        "engine_sha256": sha(engine),
        "network_sha256": sha(network),
        "config_sha256": expected_config,
        "profiles": calculated,
        "latency": summary["latency"],
        "full_acceptance": False,
        "limitations": "Timed counts and RSS reconstructed from actual raw observations. Parallel strength, race instrumentation, G04 stop p99 and host isolation require separate evidence.",
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("evidence", type=Path)
    parser.add_argument("--engine", type=Path, required=True)
    parser.add_argument("--network", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--expected-config-sha256", required=True)
    parser.add_argument("--maximum-seconds", type=int, default=600)
    parser.add_argument("--require-full", action="store_true")
    parser.add_argument("--replay-output", type=Path)
    args = parser.parse_args()
    try:
        result = verify(
            args.evidence,
            args.engine,
            args.network,
            args.config,
            args.expected_config_sha256,
            args.maximum_seconds,
            args.require_full,
            args.replay_output,
        )
        print(json.dumps(result))
        return 0
    except (ValueError, KeyError, IndexError, OSError, TypeError) as error:
        print(
            json.dumps(
                {"status": "rejected", "reason": str(error), "full_acceptance": False}
            )
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
