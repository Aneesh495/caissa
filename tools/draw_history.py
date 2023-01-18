"""Observe actual native draw decisions along prospectively fixed histories."""

import argparse
import hashlib
import json
import random
import subprocess
import time
from pathlib import Path

import chess

from tools.campaign_process import atomic
from tools.heuristic_study import avoid_decisive_matches
from verification.tactical_generation import Probe


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--engine", type=Path, required=True)
    parser.add_argument("--network", type=Path, required=True)
    parser.add_argument("--profile", type=Path, required=True)
    parser.add_argument("--expected-profile-sha256", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    avoid_decisive_matches()
    if digest(args.profile) != args.expected_profile_sha256:
        raise ValueError("draw profile differs from external identity")
    rule = json.loads(args.profile.read_text())
    if digest(args.network) != rule["network_sha256"]:
        raise ValueError("draw runtime network differs")
    args.output.mkdir(parents=True, exist_ok=False)
    started = time.time()
    maximum = rule["maximum_producer_seconds"]
    deadline = started + maximum
    active = time.monotonic()
    config = {
        "schema": "caissa-draw-history-sample-v1",
        "source_commit": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], text=True, timeout=5
        ).strip(),
        "engine_sha256": digest(args.engine),
        "network_sha256": digest(args.network),
        "profile_sha256": args.expected_profile_sha256,
        "deadline_unix": deadline,
        "maximum_seconds": maximum,
        "full_acceptance": False,
    }
    atomic(args.output / "CONFIG.json", config)
    native = None
    count = histories = 0
    raw_sha = hashlib.sha256()
    last = None
    try:
        native = Probe(
            args.engine, ["--state-probe", str(args.network.resolve())], deadline
        )
        with (args.output / "observations.jsonl").open("xb") as output:

            def observe(case, command):
                nonlocal count, last
                if time.time() >= deadline or time.monotonic() - active >= maximum:
                    raise TimeoutError("draw producer deadline exhausted")
                last = {"case": case, "command": command}
                response = native.request(command)
                if "error" in response:
                    raise ValueError("native draw path rejected: " + str(response))
                command_sha = hashlib.sha256(native.last_response).hexdigest()
                state = native.request("rules")
                record = {
                    "index": count,
                    "case": case,
                    "command": command,
                    "state_response_sha256": command_sha,
                    "rules": state,
                    "rules_response_sha256": hashlib.sha256(
                        native.last_response
                    ).hexdigest(),
                }
                line = (
                    json.dumps(record, separators=(",", ":"), allow_nan=False) + "\n"
                ).encode()
                output.write(line)
                raw_sha.update(line)
                count += 1
                if (
                    count > rule["maximum_commands"]
                    or output.tell() > rule["maximum_observation_bytes"]
                ):
                    raise ValueError("draw observation ceiling exhausted")
                atomic(
                    args.output / "PROGRESS.json",
                    {"observations": count, "histories": histories, "last": last},
                )

            for case in rule["fixed_cases"]:
                observe(
                    case["name"],
                    "reset " + ("960|" if case["chess960"] else "") + case["fen"],
                )
                for command in case["commands"]:
                    observe(case["name"], command)
                histories += 1
            rng = random.Random(rule["seed"])
            for index in range(rule["random_histories"]):
                start = rule["random_starts"][index % len(rule["random_starts"])]
                board = chess.Board(start["fen"], chess960=start["chess960"])
                name = "reachable-" + str(index)
                observe(
                    name, "reset " + ("960|" if board.chess960 else "") + start["fen"]
                )
                for _ in range(rule["maximum_game_ply"]):
                    moves = sorted(board.legal_moves, key=board.uci)
                    if not moves:
                        break
                    move = rng.choice(moves)
                    text = board.uci(move)
                    board.push(move)
                    observe(name, "move " + text)
                histories += 1
        native.close()
        (args.output / "stderr.log").write_bytes(native.stderr)
        if native.process.returncode != 0 or native.stderr or native.buffer:
            raise ValueError("draw producer native exit or transport differs")
        atomic(
            args.output / "SUMMARY.json",
            {
                **config,
                "status": "observed",
                "histories": histories,
                "observations": count,
                "observations_sha256": raw_sha.hexdigest(),
                "native_exit": native.process.returncode,
                "elapsed_seconds": time.monotonic() - active,
            },
        )
    except BaseException as error:
        atomic(
            args.output / "FAILED.json",
            {
                "reason": str(error),
                "observations": count,
                "histories": histories,
                "last": last,
            },
        )
        raise
    finally:
        if native is not None and native.process.poll() is None:
            native.close()
        if native is not None:
            (args.output / "stderr.log").write_bytes(native.stderr)


if __name__ == "__main__":
    main()
