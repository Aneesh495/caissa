"""Independent draw-history reconstruction with exact saved-program replay.

Uses python-chess for legal history and dead-material recognition. It does not
import the native observation producer or its chess decision logic.
"""

import argparse
import hashlib
import math
import os
import random
import shutil
import time
from pathlib import Path

import chess

from tools.campaign_process import atomic
from verification.bundle import strict_json
from verification.restoration_state import MASK, Shadow, hexadecimal, mix, require
from verification.tactical_generation import Probe

PROFILE_SHA256 = "4512410118ad92190c167232b2082308aa18c42e07b287fa7b281b8ecc90c583"


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def document(path, maximum=4 * 1024 * 1024):
    path = Path(path)
    require(
        path.is_file() and not path.is_symlink() and 0 < path.stat().st_size <= maximum,
        "draw document missing, linked or excessive",
    )
    return strict_json(path.read_bytes())


def typed_equal(actual, expected):
    if type(actual) is not type(expected):
        return False
    if isinstance(expected, dict):
        return actual.keys() == expected.keys() and all(
            typed_equal(actual[k], v) for k, v in expected.items()
        )
    if isinstance(expected, list):
        return len(actual) == len(expected) and all(
            typed_equal(a, b) for a, b in zip(actual, expected, strict=True)
        )
    return actual == expected


def decisions(shadow):
    board = shadow.board
    dead = board.is_insufficient_material()
    legal = list(board.legal_moves)
    terminal = "ongoing"
    if not legal:
        terminal = "checkmate" if board.is_check() else "stalemate"
    elif not shadow.synthetic and board.halfmove_clock >= 150:
        terminal = "seventy-five-move"
    elif not shadow.synthetic and board.is_fivefold_repetition():
        terminal = "fivefold"
    elif dead:
        terminal = "proven-dead-material"
    claim = terminal == "ongoing" and not shadow.synthetic
    threefold = bool(claim and board.is_repetition(3))
    fifty = bool(claim and board.halfmove_clock >= 100)
    return terminal, threefold, fifty, dead


def expected(shadow):
    terminal, threefold, fifty, dead = decisions(shadow)
    board = shadow.board
    claims = []
    if terminal == "ongoing":
        for move in list(board.legal_moves):
            text = board.uci(move)
            shadow.push(text)
            try:
                child, third, clock, _ = decisions(shadow)
                if child == "ongoing" and (third or clock):
                    claims.append(text)
            finally:
                shadow.pop()
    count = min(len(shadow.history), board.halfmove_clock + 1)
    context, power = 0, 1
    for key in reversed(shadow.history[-count:]):
        context = (context + key * power) & MASK
        power = (power * 0x9E3779B185EBCA87) & MASK
    search = shadow.key() ^ mix(
        context
        ^ mix(board.halfmove_clock + 20000)
        ^ ((count * 0xD6E8FEB86659FD93) & MASK)
    )
    if shadow.synthetic:
        search ^= mix(30000 + shadow.synthetic)
    return {
        "fen": board.fen(shredder=board.chess960, en_passant="fen"),
        "chess960": board.chess960,
        "terminal": terminal,
        "threefold_claim": threefold,
        "fifty_move_claim": fifty,
        "ended": terminal != "ongoing",
        "claimable": threefold or fifty,
        "proven_dead": dead,
        "synthetic_depth": shadow.synthetic,
        "repetitions": sum(
            key == shadow.repetition_key() for key in shadow.history[-count:]
        ),
        "key": hexadecimal(shadow.key()),
        "repetition_key": hexadecimal(shadow.repetition_key()),
        "search_key": hexadecimal(search),
        "overloads_equal": True,
        "restored": True,
        "claim_moves": sorted(claims),
    }


def schedule(rule):
    for case in rule["fixed_cases"]:
        yield case["name"], "reset " + ("960|" if case["chess960"] else "") + case[
            "fen"
        ]
        for command in case["commands"]:
            yield case["name"], command
    rng = random.Random(rule["seed"])
    for index in range(rule["random_histories"]):
        start = rule["random_starts"][index % len(rule["random_starts"])]
        board = chess.Board(start["fen"], chess960=start["chess960"])
        name = "reachable-" + str(index)
        yield name, "reset " + ("960|" if board.chess960 else "") + start["fen"]
        for _ in range(rule["maximum_game_ply"]):
            moves = sorted(board.legal_moves, key=board.uci)
            if not moves:
                break
            move = rng.choice(moves)
            text = board.uci(move)
            board.push(move)
            yield name, "move " + text


def verify(
    observations,
    summary_path,
    config_path,
    engine,
    expected_engine,
    network,
    expected_network,
    profile_path,
    expected_profile,
    expected_observations,
    output,
    *,
    maximum_seconds=240,
):
    from tools.heuristic_study import avoid_decisive_matches

    avoid_decisive_matches()
    require(
        expected_profile == PROFILE_SHA256 and digest(profile_path) == PROFILE_SHA256,
        "draw prospective profile differs",
    )
    rule, config, summary = (
        document(profile_path),
        document(config_path),
        document(summary_path),
    )
    require(
        math.isfinite(maximum_seconds)
        and 0 < maximum_seconds <= rule["maximum_independent_seconds"],
        "draw replay duration exceeds profile",
    )
    for key, value in [
        ("engine_sha256", expected_engine),
        ("network_sha256", expected_network),
        ("profile_sha256", expected_profile),
    ]:
        require(
            config.get(key) == summary.get(key) == value,
            "draw actor/profile metadata differs",
        )
    require(
        config.get("schema")
        == summary.get("schema")
        == "caissa-draw-history-sample-v1",
        "draw sample schema differs",
    )
    require(
        expected_network == rule["network_sha256"]
        and digest(network) == expected_network
        and digest(engine) == expected_engine,
        "draw externally pinned runtime differs",
    )
    require(
        type(config.get("maximum_seconds")) in {int, float}
        and 0 < config["maximum_seconds"] <= rule["maximum_producer_seconds"],
        "draw producer ceiling differs",
    )
    require(
        summary.get("status") == "observed"
        and type(summary.get("native_exit")) is int
        and summary["native_exit"] == 0,
        "draw producer native exit differs",
    )
    require(
        summary.get("observations_sha256") == expected_observations,
        "draw observation external identity differs",
    )
    observations, output = Path(observations), Path(output)
    require(
        observations.is_file()
        and not observations.is_symlink()
        and 0 < observations.stat().st_size <= rule["maximum_observation_bytes"],
        "draw raw observations missing, linked or excessive",
    )
    require(
        not output.resolve().is_relative_to(observations.parent.resolve()),
        "draw replay must preserve the original evidence",
    )
    output.mkdir(parents=True, exist_ok=False)
    saved_engine, saved_network = output / "caissa", output / "selected.cai"
    shutil.copyfile(engine, saved_engine)
    saved_engine.chmod(0o755)
    shutil.copyfile(network, saved_network)
    require(
        digest(saved_engine) == expected_engine
        and digest(saved_network) == expected_network,
        "draw copied runtime differs",
    )
    started, active = time.time(), time.monotonic()
    deadline = started + maximum_seconds
    oracle, native = Shadow(None), None
    count = 0
    raw_sha = hashlib.sha256()
    cases, outcomes, seen = set(), {}, {}
    witnesses = {
        "threefold_history": False,
        "fivefold_history": False,
        "transposition_context": False,
    }
    last = None
    try:
        native = Probe(
            saved_engine, ["--state-probe", str(saved_network.resolve())], deadline
        )
        with (
            observations.open("rb") as stream,
            (output / "native-replay.jsonl").open("xb") as replay,
        ):
            original = os.fstat(stream.fileno())
            for index, (case, command) in enumerate(schedule(rule)):
                require(
                    time.time() < deadline
                    and time.monotonic() - active < maximum_seconds,
                    "draw independent cumulative deadline exhausted",
                )
                raw = stream.readline(65537)
                require(
                    raw and len(raw) <= 65536 and raw.endswith(b"\n"),
                    "draw full observation missing or excessive",
                )
                raw_sha.update(raw)
                record = strict_json(raw)
                last = {"index": index, "case": case, "command": command}
                require(
                    type(record.get("index")) is int
                    and record["index"] == index
                    and record.get("case") == case
                    and record.get("command") == command,
                    "draw reachable history schedule differs",
                )
                if command.startswith("reset "):
                    fen = command[6:]
                    c960 = fen.startswith("960|")
                    oracle.reset(fen[4:] if c960 else fen, c960)
                elif command == "undo":
                    oracle.pop()
                else:
                    oracle.push(command[5:] if command.startswith("move ") else command)
                model = expected(oracle)
                require(
                    typed_equal(record.get("rules"), model),
                    "independent draw decision or wire type differs",
                )
                state = native.request(command)
                state_sha = hashlib.sha256(native.last_response).hexdigest()
                require(
                    "error" not in state
                    and state_sha == record["state_response_sha256"],
                    "fresh draw command response differs",
                )
                actual = native.request("rules")
                reply = hashlib.sha256(native.last_response).hexdigest()
                require(
                    typed_equal(actual, model)
                    and reply == record["rules_response_sha256"],
                    "fresh native draw decisions differ",
                )
                replay.write(
                    (
                        __import__("json").dumps(
                            {**last, "state_sha256": state_sha, "rules_sha256": reply},
                            separators=(",", ":"),
                        )
                        + "\n"
                    ).encode()
                )
                previous = seen.setdefault(model["fen"], [])
                for other in previous:
                    if other["search_key"] != model["search_key"]:
                        witnesses["transposition_context"] = True
                    if other["threefold_claim"] != model["threefold_claim"]:
                        witnesses["threefold_history"] = True
                    if {other["terminal"], model["terminal"]} == {
                        "fivefold",
                        "ongoing",
                    }:
                        witnesses["fivefold_history"] = True
                previous.append(model)
                cases.add(case)
                outcomes[model["terminal"]] = outcomes.get(model["terminal"], 0) + 1
                count += 1
                if count % 64 == 0:
                    atomic(
                        output / "PROGRESS.json",
                        {"observations": count, "histories": len(cases), "last": last},
                    )
            require(not stream.read(1), "draw raw observations have trailing records")
            after = os.fstat(stream.fileno())
            require(
                (original.st_size, original.st_mtime_ns, original.st_ino)
                == (after.st_size, after.st_mtime_ns, after.st_ino),
                "draw raw observations changed during replay",
            )
        require(
            count <= rule["maximum_commands"]
            and type(summary.get("observations")) is int
            and count == summary["observations"]
            and type(summary.get("histories")) is int
            and len(cases)
            == summary["histories"]
            == len(rule["fixed_cases"]) + rule["random_histories"],
            "draw completed counts differ",
        )
        require(raw_sha.hexdigest() == expected_observations, "draw raw bytes differ")
        require(all(witnesses.values()), "draw equal-board history witnesses missing")
        require(
            set(outcomes)
            == {
                "ongoing",
                "fivefold",
                "seventy-five-move",
                "proven-dead-material",
                "checkmate",
                "stalemate",
            },
            "draw terminal coverage incomplete",
        )
        native.close()
        require(
            native.process.returncode == 0 and not native.stderr and not native.buffer,
            "draw replay native exit or transport differs",
        )
        result = {
            "status": "passed",
            "source_commit": config["source_commit"],
            "engine_sha256": expected_engine,
            "network_sha256": expected_network,
            "profile_sha256": expected_profile,
            "observations_sha256": expected_observations,
            "observations": count,
            "histories": len(cases),
            "terminal_counts": outcomes,
            "equal_board_witnesses": witnesses,
            "native_exit": native.process.returncode,
            "elapsed_seconds": time.monotonic() - active,
            "full_gate": True,
            "full_acceptance": False,
        }
        atomic(output / "DRAW_HISTORY.json", result)
        return result
    except BaseException as error:
        atomic(
            output / "FAILED.json",
            {"reason": str(error), "observations": count, "last": last},
        )
        raise
    finally:
        if native is not None and native.process.poll() is None:
            native.close()
        if native is not None:
            (output / "stderr.log").write_bytes(native.stderr)


def main():
    parser = argparse.ArgumentParser()
    for name in [
        "observations",
        "summary",
        "config",
        "engine",
        "network",
        "profile",
        "output",
    ]:
        parser.add_argument("--" + name, type=Path, required=True)
    for name in ["engine", "network", "profile", "observations"]:
        parser.add_argument("--expected-" + name + "-sha256", required=True)
    parser.add_argument("--maximum-seconds", type=float, default=240)
    args = parser.parse_args()
    import json

    try:
        result = verify(
            args.observations,
            args.summary,
            args.config,
            args.engine,
            args.expected_engine_sha256,
            args.network,
            args.expected_network_sha256,
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
