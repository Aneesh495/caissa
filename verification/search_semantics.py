"""Exhaustive external-board minimax and actual table/search replay.

No native observation-producer, search or training code is imported. Classical
contract1 is interpreted by the existing independently authored board oracle.
"""

import argparse
import functools
import hashlib
import json
import math
import os
import random
import shutil
import time
from pathlib import Path

import chess

from tools.campaign_process import atomic
from verification.bundle import strict_json
from verification.classical import evaluate
from verification.draw_history import typed_equal
from verification.tactical_generation import Probe

PROFILE_SHA256 = "47940062c5092ce5fc3e964df8b498d5eaa6d8aca26f0d95eb4e2034725dda71"


def require(condition, reason):
    if not condition:
        raise ValueError(reason)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def document(path):
    path = Path(path)
    require(
        path.is_file()
        and not path.is_symlink()
        and 0 < path.stat().st_size <= 4 * 1024 * 1024,
        "search metadata missing, linked or excessive",
    )
    return strict_json(path.read_bytes())


def schedule(rule):
    rng = random.Random(rule["table_seed"])
    for i in range(rule["table_samples"]):
        key = rng.getrandbits(64)
        other = key ^ (1 << 48)
        a, b = i % 63, (i + 17) % 63
        score = rule["table_scores"][i % len(rule["table_scores"])]
        depth, bound, ply = [0, 8, 16, 64][i % 4], 1 + i % 3, [0, 1, 7, 127][i % 4]
        commands = [
            "clear",
            "new",
            f"store {key:016x} {a} {b} {score} {i-48} {depth} {bound} {ply} end",
        ]
        commands += [f"probe {key:016x} {read_ply}" for read_ply in [0, 3, 17, 127]]
        commands += [
            f"probe {other:016x} 0",
            f"hint {other:016x} {a} {b} 8",
            f"probe {other:016x} 0",
            f"store {key:016x} {b} {a} 7 -1 0 2 0 end",
            f"probe {key:016x} 7",
            "clear",
            f"probe {key:016x} 0",
        ]
        for command in commands:
            yield "table-" + str(i), "table", command, None
    cases = {case["id"]: case for case in rule["cases"]}
    for case in rule["cases"]:
        for depth in case["depths"]:
            for flags in rule["exact_flags"]:
                for seed in rule["exact_seeds"]:
                    name = f"exact/{case['id']}/{depth}/{flags}/{seed}"
                    yield name, "clear", "clear", None
                    yield name, "exact", query(case, depth, flags, seed, rule), (
                        case,
                        depth,
                        flags,
                    )
    case = cases["lmr-window-regression"]
    for flags in rule["lmr_witness_flags"]:
        name = "regression/lmr/" + str(flags)
        yield name, "clear", "clear", None
        yield name, "regression", query(case, 5, flags, 0, rule), (case, 5, flags)
    for identity in rule["ablation_cases"]:
        case = cases[identity]
        for bit in [0, *rule["ablation_switch_bits"]]:
            flags, depth = (
                rule["ablation_reference_flags"] ^ bit,
                rule["ablation_depth"],
            )
            name = f"ablation/{identity}/{bit}"
            yield name, "clear", "clear", None
            yield name, "ablation", query(case, depth, flags, 0, rule), (
                case,
                depth,
                flags,
            )


def query(case, depth, flags, seed, rule):
    return f"search {depth} {flags} {seed} {rule['maximum_native_nodes']} {int(case['chess960'])}|{case['fen']}|{' '.join(case['moves'])}"


class Table:
    def __init__(self):
        self.age, self.entries, self.hints = 0, {}, {}

    def run(self, command):
        words = command.split()
        operation = words[0]
        if operation == "clear":
            self.entries.clear()
            self.hints.clear()
            return {"operation": operation, "bytes": 1048576, "hashfull": 0}
        if operation == "new":
            self.age = (self.age + 1) % 256
            return {"operation": operation}
        key, read_ply = words[1], 0
        if operation == "store":
            source, target, value, evaluation, depth, bound, read_ply = map(
                int, words[2:9]
            )
            move = source | (target << 7)
            old = self.entries.get(key)
            if old is not None and old["depth"] > depth + 3 and bound != 1:
                old["move"] = move
            else:
                stored = (
                    value + read_ply
                    if value >= 29872
                    else value - read_ply if value <= -29872 else value
                )
                self.entries[key] = {
                    "key": key,
                    "move": move,
                    "stored_score": stored,
                    "evaluation": evaluation,
                    "depth": depth,
                    "bound": bound,
                    "age": self.age,
                }
        elif operation == "hint":
            source, target = map(int, words[2:4])
            self.hints[key] = source | (target << 7)
        else:
            read_ply = int(words[2])
        stored = self.entries.get(key)
        entry = None if stored is None else dict(stored)
        if entry is not None:
            value = entry["stored_score"]
            entry["score"] = (
                value - read_ply
                if value >= 29872
                else value + read_ply if value <= -29872 else value
            )
        return {
            "operation": operation,
            "query_key": key,
            "query_ply": read_ply,
            "entry": entry,
            "hint": self.hints.get(key),
        }


def board_for(case):
    board = chess.Board(case["fen"], chess960=case["chess960"])
    require(board.is_valid(), "search oracle fixture invalid")
    for move in case["moves"]:
        board.push_uci(move)
    return board


def termination(board):
    if board.is_checkmate():
        return "checkmate"
    if board.is_stalemate():
        return "stalemate"
    if board.halfmove_clock >= 150:
        return "seventy-five-move"
    if board.is_fivefold_repetition():
        return "fivefold"
    if board.is_insufficient_material():
        return "proven-dead-material"
    return "ongoing"


def current_claim(board):
    return board.halfmove_clock >= 100 or board.is_repetition(3)


class Minimax:
    def __init__(self, tick, ceiling):
        self.tick, self.ceiling, self.nodes = tick, ceiling, 0
        self.static = functools.lru_cache(maxsize=100000)(evaluate)
        self.cache = {}

    def terminal_value(self, board, ply):
        reason = termination(board)
        return (
            (-30000 + ply if reason == "checkmate" else 0)
            if reason != "ongoing"
            else None
        )

    def solve(self, board, depth, ply):
        self.nodes += 1
        require(
            self.nodes <= self.ceiling,
            "search exhaustive oracle node ceiling exhausted",
        )
        if self.nodes % 256 == 0:
            self.tick()
        terminal = self.terminal_value(board, ply)
        if terminal is not None:
            return terminal
        if depth == 0:
            score = self.static(board.fen(en_passant="fen"))
            return (
                max(0, score)
                if board.can_claim_fifty_moves()
                or board.can_claim_threefold_repetition()
                else score
            )
        best = 0 if current_claim(board) else -32000
        for move in list(board.legal_moves):
            board.push(move)
            try:
                value = -self.solve(board, depth - 1, ply + 1)
                # The mover may announce a drawing move before completing it.
                # A mating move remains a positive continuation, so clipping
                # negative continuations cannot hide mate precedence.
                if current_claim(board):
                    value = max(0, value)
            finally:
                board.pop()
            best = max(best, value)
        return best

    def root(self, case, depth):
        key = case["id"], depth
        if key in self.cache:
            return self.cache[key]
        before = self.nodes
        board = board_for(case)
        terminal = self.terminal_value(board, 0)
        moves = {}
        if terminal is None:
            for move in list(board.legal_moves):
                text = board.uci(move)
                board.push(move)
                try:
                    score = -self.solve(board, depth - 1, 1)
                    if current_claim(board):
                        score = max(0, score)
                finally:
                    board.pop()
                moves[text] = score
            score = (
                max([0] + list(moves.values()))
                if current_claim(board)
                else max(moves.values())
            )
        else:
            score = terminal
        result = {
            "score": score,
            "move_values": moves,
            "terminal": termination(board),
            "nodes": self.nodes - before,
            "current_claim": current_claim(board),
        }
        self.cache[key] = result
        return result


def validate_search(actual, case, depth, flags, oracle, exact):
    board = board_for(case)
    require(
        type(actual) is dict and actual.get("operation") == "search",
        "search native response shape differs",
    )
    for field in [
        "score",
        "depth",
        "nodes",
        "requested_depth",
        "flags",
        "seed",
        "node_limit",
    ]:
        require(type(actual.get(field)) is int, "search wire integer type differs")
    require(
        actual.get("fen") == board.fen(shredder=board.chess960, en_passant="fen")
        and type(actual.get("chess960")) is bool
        and actual["chess960"] == board.chess960
        and actual["flags"] == flags
        and actual["requested_depth"] == depth
        and actual.get("terminal") == oracle["terminal"],
        "search actual root or requested algorithm differs",
    )
    require(
        actual.get("interrupted") is False
        and actual["depth"] == (depth if oracle["terminal"] == "ongoing" else 0),
        "search did not finish its frozen depth",
    )
    require(
        0 <= actual["nodes"] <= actual["node_limit"] == 100000
        and -30000 <= actual["score"] <= 30000,
        "search actual score or resource ceiling differs",
    )
    legal = {board.uci(move) for move in board.legal_moves}
    if oracle["terminal"] != "ongoing":
        require(
            actual["bestmove"] == "0000" and actual["pv"] == [],
            "terminal search fabricated a move",
        )
    else:
        require(
            actual["bestmove"] in legal
            and actual["pv"]
            and actual["pv"][0] == actual["bestmove"],
            "search best move/PV does not match its legal root",
        )
        for text in actual["pv"]:
            move = board.parse_uci(text)
            require(move in board.legal_moves, "search PV contains an illegal move")
            board.push(move)
    if exact:
        require(
            actual["score"] == oracle["score"],
            "independent exhaustive minimax value differs",
        )
        if oracle["terminal"] == "ongoing":
            allowed = oracle["move_values"].get(actual["bestmove"]) == oracle[
                "score"
            ] or (oracle["current_claim"] and oracle["score"] == 0)
            require(allowed, "search best move is not an independent minimax optimum")
    stats = actual.get("stats")
    require(
        type(stats) is dict
        and stats
        and all(type(v) is int and v >= 0 for v in stats.values()),
        "search work counters malformed",
    )
    for flag, fields in [
        (1, ["table_hits", "table_cutoffs"]),
        (8, ["ordering_hint_hits"]),
        (16, ["lmr_searches"]),
        (32, ["null_cutoffs"]),
        (64, ["qnodes"]),
        (1024, ["futility_skips"]),
        (2048, ["evaluation_cache_hits"]),
    ]:
        require(
            flags & flag or all(stats.get(field) == 0 for field in fields),
            "disabled search heuristic recorded work",
        )
    require(
        stats.get("neural_evaluations") == 0,
        "classical minimax probe used a neural model",
    )


def verify(
    observations,
    summary_path,
    config_path,
    engine,
    expected_engine,
    profile_path,
    expected_profile,
    expected_observations,
    output,
    *,
    maximum_seconds=600,
):
    from tools.heuristic_study import avoid_decisive_matches

    avoid_decisive_matches()
    require(
        expected_profile == PROFILE_SHA256 and sha(profile_path) == PROFILE_SHA256,
        "search prospective profile differs",
    )
    rule, config, summary = (
        document(profile_path),
        document(config_path),
        document(summary_path),
    )
    require(
        math.isfinite(maximum_seconds)
        and 0 < maximum_seconds <= rule["maximum_independent_seconds"],
        "search independent duration exceeds profile",
    )
    for field, value in [
        ("engine_sha256", expected_engine),
        ("profile_sha256", expected_profile),
    ]:
        require(
            config.get(field) == summary.get(field) == value,
            "search sample actor/profile identity differs",
        )
    require(
        config.get("schema")
        == summary.get("schema")
        == "caissa-search-semantics-sample-v1"
        and summary.get("status") == "observed"
        and type(summary.get("native_exit")) is int
        and summary["native_exit"] == 0,
        "search sample schema or actual exit differs",
    )
    require(
        sha(engine) == expected_engine
        and summary.get("observations_sha256") == expected_observations,
        "search externally pinned program/raw identity differs",
    )
    expected_count = sum(1 for _ in schedule(rule))
    require(
        type(summary.get("observations")) is int
        and summary["observations"] == expected_count <= rule["maximum_commands"],
        "full frozen command inventory differs",
    )
    require(
        type(config.get("maximum_seconds")) in {int, float}
        and math.isfinite(config["maximum_seconds"])
        and 0 < config["maximum_seconds"] <= rule["maximum_producer_seconds"],
        "search producer duration exceeds profile",
    )
    observations, output = Path(observations), Path(output)
    require(
        observations.is_file()
        and not observations.is_symlink()
        and 0 < observations.stat().st_size <= rule["maximum_observation_bytes"],
        "search observations missing, linked or excessive",
    )
    require(
        not output.resolve().is_relative_to(observations.parent.resolve()),
        "search replay must preserve the original evidence",
    )
    output.mkdir(parents=True, exist_ok=False)
    saved = output / "caissa"
    shutil.copyfile(engine, saved)
    saved.chmod(0o755)
    require(sha(saved) == expected_engine, "copied search program differs")
    active, deadline = time.monotonic(), time.time() + maximum_seconds

    def tick():
        require(
            time.time() < deadline and time.monotonic() - active < maximum_seconds,
            "search independent cumulative deadline exhausted",
        )

    oracle, table = Minimax(tick, rule["maximum_oracle_nodes"]), Table()
    native, count, last = None, 0, None
    raw_sha = hashlib.sha256()
    categories = {"table": 0, "clear": 0, "exact": 0, "regression": 0, "ablation": 0}
    ablations, regressions = [], []
    try:
        native = Probe(saved, "--search-probe", deadline)
        with (
            observations.open("rb") as stream,
            (output / "native-replay.jsonl").open("xb") as replay,
        ):
            original = os.fstat(stream.fileno())
            for index, (name, kind, command, case_info) in enumerate(schedule(rule)):
                tick()
                last = {"index": index, "name": name, "kind": kind, "command": command}
                raw = stream.readline(65537)
                require(
                    raw and raw.endswith(b"\n") and len(raw) <= 65536,
                    "missing or excessive full search observation",
                )
                raw_sha.update(raw)
                row = strict_json(raw)
                require(
                    all(typed_equal(row.get(k), v) for k, v in last.items()),
                    "search frozen command schedule differs",
                )
                actual = row.get("actual")
                if case_info is None:
                    require(
                        typed_equal(actual, table.run(command)),
                        "independent table bound/mate/identity differs",
                    )
                else:
                    case, depth, flags = case_info
                    expected = oracle.root(case, depth)
                    validate_search(
                        actual,
                        case,
                        depth,
                        flags,
                        expected,
                        kind in {"exact", "regression"},
                    )
                    if kind == "ablation":
                        ablations.append(
                            {
                                "name": name,
                                "score": actual["score"],
                                "exhaustive": expected["score"],
                                "delta": actual["score"] - expected["score"],
                                "nodes": actual["nodes"],
                                "stats": actual["stats"],
                            }
                        )
                    if kind == "regression":
                        regressions.append(
                            {
                                "name": name,
                                "score": actual["score"],
                                "exhaustive": expected["score"],
                                "stats": actual["stats"],
                            }
                        )
                observed = native.request(command)
                reply = hashlib.sha256(native.last_response).hexdigest()
                require(
                    typed_equal(actual, observed)
                    and row.get("response_sha256") == reply,
                    "fresh native search/table reply differs",
                )
                replay.write(
                    (
                        json.dumps(
                            {**last, "response_sha256": reply}, separators=(",", ":")
                        )
                        + "\n"
                    ).encode()
                )
                categories[kind] += 1
                count += 1
                if count % 64 == 0:
                    atomic(
                        output / "PROGRESS.json",
                        {
                            "observations": count,
                            "oracle_nodes": oracle.nodes,
                            "last": last,
                        },
                    )
            require(not stream.read(1), "search observations have trailing records")
            after = os.fstat(stream.fileno())
            require(
                (original.st_size, original.st_mtime_ns, original.st_ino)
                == (after.st_size, after.st_mtime_ns, after.st_ino),
                "search observations changed during replay",
            )
        require(
            type(summary.get("observations")) is int
            and count == summary["observations"] <= rule["maximum_commands"],
            "search completed observation count differs",
        )
        require(
            raw_sha.hexdigest() == expected_observations,
            "search raw observation bytes differ",
        )
        require(
            len(ablations)
            == len(rule["ablation_cases"]) * (1 + len(rule["ablation_switch_bits"]))
            and len(regressions) == 4,
            "search ablation/regression inventory differs",
        )
        require(
            any(
                row["stats"]["lmr_searches"] > 0 and row["stats"]["researches"] > 0
                for row in regressions
            ),
            "LMR regression did not exercise recovery",
        )
        native.close()
        require(
            native.process.returncode == 0 and not native.stderr and not native.buffer,
            "search replay native exit or transport differs",
        )
        atomic(
            output / "ORACLES.json",
            [
                {"case": key[0], "depth": key[1], **value}
                for key, value in oracle.cache.items()
            ],
        )
        atomic(
            output / "ABLATIONS.json",
            {
                "scope": "Fixed-depth work/value observations, no playing-strength conclusion",
                "rows": ablations,
                "regressions": regressions,
            },
        )
        result = {
            "status": "passed",
            "source_commit": config["source_commit"],
            "engine_sha256": expected_engine,
            "profile_sha256": expected_profile,
            "observations_sha256": expected_observations,
            "observations": count,
            "categories": categories,
            "exhaustive_positions_depths": len(oracle.cache),
            "oracle_nodes": oracle.nodes,
            "selective_value_differences": sum(row["delta"] != 0 for row in ablations),
            "regression_queries": len(regressions),
            "native_exit": native.process.returncode,
            "elapsed_seconds": time.monotonic() - active,
            "full_gate": True,
            "full_acceptance": False,
        }
        atomic(output / "SEARCH_SEMANTICS.json", result)
        return result
    except BaseException as error:
        atomic(
            output / "FAILED.json",
            {
                "reason": str(error),
                "observations": count,
                "oracle_nodes": oracle.nodes,
                "last": last,
            },
        )
        raise
    finally:
        if native is not None and native.process.poll() is None:
            native.close()
        if native is not None:
            (output / "stderr.log").write_bytes(native.stderr)


def main():
    parser = argparse.ArgumentParser()
    for name in ["observations", "summary", "config", "engine", "profile", "output"]:
        parser.add_argument("--" + name, type=Path, required=True)
    for name in ["engine", "profile", "observations"]:
        parser.add_argument("--expected-" + name + "-sha256", required=True)
    parser.add_argument("--maximum-seconds", type=float, default=600)
    args = parser.parse_args()
    try:
        result = verify(
            args.observations,
            args.summary,
            args.config,
            args.engine,
            args.expected_engine_sha256,
            args.profile,
            args.expected_profile_sha256,
            args.expected_observations_sha256,
            args.output,
            maximum_seconds=args.maximum_seconds,
        )
        print(json.dumps(result))
    except (ValueError, OSError, TimeoutError, KeyError, TypeError) as error:
        print(
            json.dumps(
                {"status": "failed", "reason": str(error), "full_acceptance": False}
            )
        )
        raise SystemExit(1)


if __name__ == "__main__":
    main()
