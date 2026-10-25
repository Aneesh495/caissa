"""Read-only independent reconstruction of the frozen neural runtime pilot.

Reads native transport records directly. Imports no producer, arena, search or
training implementation and does not execute an engine or infer Elo.
"""

import argparse
import hashlib
import json
import random
import re
import statistics
from pathlib import Path

import chess

from verification.bundle import strict_json

PROFILE_SHA256 = "91add4ccf9a33f46358ca5381f2dbf1679eae02697a0c891b452e8749ad4821a"
WORK = {
    "accumulator_pushes",
    "accumulator_materializations",
    "accumulator_copies",
    "accumulator_refreshes",
    "accumulator_delta_squares",
}
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


def load(path, maximum=4 * 1024 * 1024):
    require(
        path.is_file() and not path.is_symlink() and path.stat().st_size <= maximum,
        "runtime metadata file bound",
    )
    return strict_json(path.read_bytes())


def native(row, config):
    lines = row["lines"]
    require(
        isinstance(lines, list)
        and 1 <= len(lines) <= 5000
        and all(
            isinstance(line, str)
            and len(line) <= 16384
            and not any(c in line for c in "\r\n\0")
            for line in lines
        ),
        "native runtime line bound",
    )
    best = [line for line in lines if line.startswith("bestmove ")]
    require(
        len(best) == 1 and lines[-1] == best[0] and best[0].split()[1] == row["move"],
        "native runtime bestmove differs",
    )
    stats_lines = [line for line in lines if line.startswith("info string stats ")]
    require(len(stats_lines) == 1, "native runtime statistics missing or duplicated")
    fields = stats_lines[0].split()[3:]
    require(len(fields) % 2 == 0, "native runtime counter layout")
    counters = {}
    for key, value in zip(fields[::2], fields[1::2], strict=True):
        require(
            key not in counters and re.fullmatch(r"\d+", value),
            "native runtime repeated or invalid counter",
        )
        counters[key] = int(value)
    require(
        set(counters)
        == (COUNTERS if row["arm"] == "archived-eager" else COUNTERS | WORK),
        "native runtime counter inventory",
    )
    require(
        counters == row["observed"]["stats"],
        "saved parsed counters differ from native bytes",
    )
    require(
        0 < counters["visited_nodes"] <= config["nodes"]
        and counters["completed_depth_nodes"] <= counters["visited_nodes"]
        and counters["tt_cutoffs"] <= counters["tt_hits"]
        and counters["qnodes"] <= counters["visited_nodes"],
        "native runtime counter relation",
    )
    infos = []
    for line in lines:
        if not line.startswith("info depth "):
            continue
        words = line.split()
        require(
            "pv" in words and "score" in words, "native runtime info lacks PV or score"
        )
        board = chess.Board(row["position"]["fen"])
        for text in words[words.index("pv") + 1 :]:
            move = chess.Move.from_uci(text)
            require(move in board.legal_moves, "native runtime illegal PV")
            board.push(move)
        infos.append(re.sub(r" (?:time|nps) \d+", "", line))
    require(infos, "native runtime has no completed iteration")
    board = chess.Board(row["position"]["fen"])
    require(
        chess.Move.from_uci(row["move"]) in board.legal_moves,
        "native runtime illegal bestmove",
    )
    request = row["request"]
    require(
        request["go"] == "go nodes " + str(config["nodes"])
        and request["position"] == "position fen " + row["position"]["fen"],
        "runtime native request differs from frozen workload",
    )
    start, end = request["started_monotonic_ns"], request["completed_monotonic_ns"]
    require(
        type(start) is int and type(end) is int and end > start,
        "runtime request timestamps invalid",
    )
    elapsed = (end - start) / 1e6
    require(
        type(row["roundtrip_ms"]) in {int, float}
        and abs(elapsed - row["roundtrip_ms"]) < 1e-9,
        "runtime wall duration differs from transport timestamps",
    )
    return {
        "bestmove": best[0],
        "infos": infos,
        "counters": {
            k: v
            for k, v in counters.items()
            if k not in WORK | {"elapsed_ms", "eval_ns"}
        },
    }


def verify(root, profile, expected_engine, expected_reference):
    require(
        hashlib.sha256(profile.read_bytes()).hexdigest() == PROFILE_SHA256,
        "runtime prospective profile pin differs",
    )
    rule = load(profile)
    config = rule["measurement"]
    envelope = load(root / "CONFIG.json")
    require(
        envelope["profile_sha256"] == PROFILE_SHA256
        and envelope["engine_sha256"] == expected_engine
        and envelope["reference_sha256"] == expected_reference
        and envelope["network_sha256"] == rule["network_sha256"],
        "runtime externally pinned actor differs",
    )
    require(
        expected_reference in {v["sha256"] for v in rule["references"].values()},
        "runtime reference is outside frozen platforms",
    )
    path = root / "observations.jsonl"
    require(
        path.is_file()
        and not path.is_symlink()
        and 0 < path.stat().st_size <= 32 * 1024 * 1024,
        "runtime raw observation byte bound",
    )
    observations = [strict_json(line) for line in path.read_bytes().splitlines()]
    expected_queries = (
        len(config["weights"])
        * len(config["evaluation_cache"])
        * config["repeats"]
        * len(config["positions"])
        * len(config["arms"])
    )
    require(
        len(observations) == expected_queries,
        "runtime complete query inventory differs",
    )
    sessions = load(root / "SESSIONS.json")
    require(
        len(sessions)
        == len(config["weights"])
        * len(config["evaluation_cache"])
        * len(config["arms"]),
        "runtime session inventory differs",
    )
    seen = set()
    for session in sessions:
        key = (session["weight"], session["cached"], session["arm"])
        require(key not in seen, "runtime duplicate session")
        seen.add(key)
        require(
            session["arm"] in config["arms"]
            and session["weight"] in config["weights"]
            and type(session["cached"]) is bool,
            "runtime unknown session",
        )
        commands = session["commands"]
        require(len(commands) == len(set(commands)), "runtime duplicate option command")
        require(
            "setoption name Neural Weight value " + str(session["weight"]) in commands
            and "setoption name Threads value 1" in commands
            and "setoption name Evaluation Cache value "
            + str(session["cached"]).lower()
            in commands
            and "setoption name Use Neural value true" in commands,
            "runtime configured evaluator or resources differ",
        )
        lazy_commands = [
            c for c in commands if c.startswith("setoption name Lazy Neural")
        ]
        require(
            lazy_commands
            == (
                []
                if session["arm"] == "archived-eager"
                else [
                    "setoption name Lazy Neural value "
                    + str(session["arm"] == "stack-lazy").lower()
                ]
            ),
            "runtime deferred/eager arm configuration differs",
        )
    rng = random.Random(config["order_seed"])
    index = 0
    groups = []
    for weight in config["weights"]:
        for cached in config["evaluation_cache"]:
            for repeat in range(config["repeats"]):
                for position in config["positions"]:
                    order = rng.sample(config["arms"], len(config["arms"]))
                    expected = None
                    group = {}
                    for arm in order:
                        row = observations[index]
                        index += 1
                        require(
                            row["arm"] == arm
                            and row["weight"] == weight
                            and type(row["cached"]) is bool
                            and row["cached"] == cached
                            and row["repeat"] == repeat
                            and row["position"] == position
                            and row["order"] == order,
                            "runtime randomized paired inventory differs",
                        )
                        current = native(row, config)
                        require(
                            expected is None or current == expected,
                            "runtime archived/eager/deferred exact search differs",
                        )
                        expected = current
                        group[arm] = row
                    groups.append(group)
    summary = load(root / "SUMMARY.json")
    require(
        summary["status"] == "passed"
        and summary["queries"] == expected_queries
        and summary["exact_triplets"] == len(groups)
        and summary["full_acceptance"] is False,
        "runtime summary sample or claim differs",
    )
    results = []
    for weight in config["weights"]:
        for cached in config["evaluation_cache"]:
            selected = [
                g
                for g in groups
                if g["stack-lazy"]["weight"] == weight
                and g["stack-lazy"]["cached"] == cached
            ]
            expected = [
                r
                for r in summary["results"]
                if r["weight"] == weight and r["cached"] == cached
            ]
            require(
                len(expected) == 1, "runtime summary missing or duplicate result group"
            )
            result = {"weight": weight, "cached": cached}
            for baseline, field in [
                ("archived-eager", "median_lazy_to_archived_wall_ratio"),
                ("stack-eager", "median_lazy_to_stack_eager_wall_ratio"),
            ]:
                ratios = [
                    g["stack-lazy"]["roundtrip_ms"] / g[baseline]["roundtrip_ms"]
                    for g in selected
                ]
                require(
                    ratios == expected[0]["paired_ratios"][baseline]
                    and statistics.median(ratios) == expected[0][field],
                    "runtime reconstructed timing ratios differ",
                )
                result[field] = statistics.median(ratios)
            for arm in ["stack-eager", "stack-lazy"]:
                for counter in WORK:
                    require(
                        sum(g[arm]["observed"]["stats"][counter] for g in selected)
                        == expected[0]["work"][arm][counter],
                        "runtime work-counter sum differs",
                    )
            results.append(result)
    return {
        "status": "passed",
        "queries": expected_queries,
        "exact_triplets": len(groups),
        "results": results,
        "engine_sha256": expected_engine,
        "reference_sha256": expected_reference,
        "raw_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "scope": "Read-only native transcript and randomized runtime reconstruction. No fresh engine execution, Elo or full acceptance.",
        "full_acceptance": False,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("evidence", type=Path)
    parser.add_argument(
        "--profile", type=Path, default=Path("config/deferred-neural-v1.json")
    )
    parser.add_argument("--expected-engine-sha256", required=True)
    parser.add_argument("--expected-reference-sha256", required=True)
    args = parser.parse_args()
    try:
        print(
            json.dumps(
                verify(
                    args.evidence,
                    args.profile,
                    args.expected_engine_sha256,
                    args.expected_reference_sha256,
                ),
                allow_nan=False,
            )
        )
    except (ValueError, KeyError, TypeError, OSError) as error:
        print(json.dumps({"status": "rejected", "reason": str(error)}))
        raise SystemExit(1)


if __name__ == "__main__":
    main()
