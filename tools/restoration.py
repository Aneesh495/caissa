"""Bounded raw observations of actual native make/unmake operations."""

import argparse
import hashlib
import json
import random
import re
import subprocess
import time
from pathlib import Path

import chess

from tools.campaign_process import atomic
from tools.heuristic_study import avoid_decisive_matches
from tools.restoration_journal import open_journal
from verification.tactical_generation import Probe

PROFILE_SHA256 = "6cde330d87e49084135760cb737f3c2756a594a69b4ed709e21b98df5f9e584c"


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--engine", type=Path, required=True)
    parser.add_argument("--network", type=Path, required=True)
    parser.add_argument(
        "--profile", type=Path, default=Path("config/restoration-v1.json")
    )
    parser.add_argument("--expected-profile-sha256", required=True)
    parser.add_argument("--pairs", type=int, default=1000000)
    parser.add_argument("--maximum-seconds", type=float, default=1800)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--source-commit")
    parser.add_argument("--gzip-journals", action="store_true")
    args = parser.parse_args()
    avoid_decisive_matches()
    if (
        args.expected_profile_sha256 != PROFILE_SHA256
        or digest(args.profile) != PROFILE_SHA256
    ):
        raise ValueError("restoration producer prospective profile differs")
    rule = json.loads(args.profile.read_text())
    if (
        not 1 <= args.pairs <= rule["transitions"]
        or not 0 < args.maximum_seconds <= rule["maximum_producer_seconds"]
    ):
        raise ValueError("restoration count or duration exceeds original profile")
    if digest(args.network) != rule["network_sha256"]:
        raise ValueError("restoration selected network differs")
    source_commit = (
        args.source_commit
        or subprocess.check_output(
            ["git", "rev-parse", "HEAD"], text=True, timeout=5
        ).strip()
    )
    if not re.fullmatch(r"[0-9a-f]{40}", source_commit):
        raise ValueError("restoration source commit malformed")
    if args.source_commit is not None:
        source = subprocess.check_output(
            ["git", "show", source_commit + ":tools/restoration.py"], timeout=5
        )
        if hashlib.sha256(source).hexdigest() != digest(__file__):
            raise ValueError("restoration producer differs from pinned source commit")
    args.output.mkdir(parents=True, exist_ok=False)
    started, active = time.time(), time.monotonic()
    deadline = started + args.maximum_seconds
    engine_sha, network_sha = digest(args.engine), digest(args.network)
    atomic(
        args.output / "CONFIG.json",
        {
            "schema": "caissa-restoration-sample-v1",
            "pairs": args.pairs,
            "engine_sha256": engine_sha,
            "network_sha256": network_sha,
            "profile_sha256": PROFILE_SHA256,
            "source_commit": source_commit,
            "started_unix": started,
            "deadline_unix": deadline,
            "maximum_seconds": args.maximum_seconds,
            "maximum_observation_bytes": rule["maximum_observation_bytes"],
            "full_acceptance": False,
            "journal_encoding": "gzip-v1" if args.gzip_journals else "plain-jsonl-v1",
        },
    )
    native = None
    closed = False
    completed = requests = nulls = resets = 0
    last_command = None
    partial = None
    observation_sha = hashlib.sha256()
    rng = random.Random(rule["seed"])
    board = None
    try:
        native = Probe(
            args.engine, ["--state-probe", str(args.network.resolve())], deadline
        )
        journal = args.output / ("observations.jsonl.gz" if args.gzip_journals else "observations.jsonl")
        with open_journal(journal, "xb", compressed=args.gzip_journals, maximum_bytes=rule["maximum_observation_bytes"]) as output:

            def check():
                if (
                    time.time() >= deadline
                    or time.monotonic() - active >= args.maximum_seconds
                ):
                    raise TimeoutError(
                        "restoration producer cumulative deadline exhausted"
                    )

            def ask(command):
                nonlocal requests, last_command
                check()
                last_command = command
                result = native.request(command)
                requests += 1
                if "error" in result:
                    raise ValueError(
                        "native restoration request rejected: " + str(result)
                    )
                return result, hashlib.sha256(native.last_response).hexdigest()

            def save(record):
                raw = (
                    json.dumps(record, separators=(",", ":"), allow_nan=False) + "\n"
                ).encode()
                output.write(raw)
                observation_sha.update(raw)
                if output.tell() > rule["maximum_observation_bytes"]:
                    raise ValueError(
                        "restoration raw observation byte ceiling exhausted"
                    )

            for index in range(args.pairs):
                check()
                if (
                    board is None
                    or not any(board.legal_moves)
                    or len(board.move_stack) >= rule["maximum_game_ply"]
                ):
                    fixture = rule["fixtures"][
                        (index // rule["maximum_game_ply"]) % len(rule["fixtures"])
                    ]
                    board = chess.Board(fixture["fen"], chess960=fixture["chess960"])
                    text = (
                        "reset " + ("960|" if board.chess960 else "") + fixture["fen"]
                    )
                    before, reply_sha = ask(text)
                    resets += 1
                    save(
                        {
                            "kind": "reset",
                            "index": index,
                            "fen": fixture["fen"],
                            "chess960": board.chess960,
                            "state": before,
                            "reply_sha256": reply_sha,
                        }
                    )
                if index % rule["null_every"] == 0 and not board.is_check():
                    sequence = []
                    for command in ["null", "null", "undo", "undo"]:
                        state, reply_sha = ask(command)
                        sequence.append(
                            {
                                "command": command,
                                "state": state,
                                "reply_sha256": reply_sha,
                            }
                        )
                    if sequence[-1]["state"] != before:
                        raise ValueError(
                            "nested null did not restore complete native state"
                        )
                    save({"kind": "null", "index": index, "states": sequence})
                    nulls += 1
                prefix = fixture.get("prefix", [])
                legal = sorted(board.uci(move) for move in board.legal_moves)
                move = (
                    prefix[len(board.move_stack)]
                    if len(board.move_stack) < len(prefix)
                    else legal[rng.randrange(len(legal))]
                )
                partial = {"index": index, "move": move}
                after, after_sha = ask("move " + move)
                partial["after"] = after
                restored, restored_sha = ask("undo")
                partial["restored"] = restored
                if restored != before:
                    raise ValueError(
                        "make/unmake did not restore complete native state"
                    )
                committed, commit_sha = ask("move " + move)
                if committed != after or commit_sha != after_sha:
                    raise ValueError("committed native state differs from trial move")
                board.push_uci(move)
                before = committed
                save(
                    {
                        "kind": "trial",
                        "index": index,
                        "move": move,
                        "after": after,
                        "restored": restored,
                        "after_reply_sha256": after_sha,
                        "restored_reply_sha256": restored_sha,
                        "commit_reply_sha256": commit_sha,
                    }
                )
                completed += 1
                partial = None
                if completed % 1024 == 0 or completed == args.pairs:
                    output.flush()
                    atomic(
                        args.output / "PROGRESS.json",
                        {
                            "pairs": completed,
                            "requests": requests,
                            "resets": resets,
                            "null_branches": nulls,
                            "raw_bytes": output.tell(),
                            "elapsed_seconds": time.monotonic() - active,
                            "unix": time.time(),
                        },
                    )
            output.flush()
        native.close()
        closed = True
        if native.process.returncode != 0 or native.stderr:
            raise ValueError("native restoration process exit or stderr failure")
        if digest(args.engine) != engine_sha or digest(args.network) != network_sha:
            raise ValueError("restoration actor bytes changed during observations")
        atomic(
            args.output / "SUMMARY.json",
            {
                "schema": "caissa-restoration-summary-v1",
                "status": "observed",
                "pairs": completed,
                "requests": requests,
                "resets": resets,
                "null_branches": nulls,
                "engine_sha256": engine_sha,
                "network_sha256": network_sha,
                "profile_sha256": PROFILE_SHA256,
                "observations_sha256": observation_sha.hexdigest(),
                "elapsed_seconds": time.monotonic() - active,
                "native_exit": native.process.returncode,
                "full_acceptance": False,
            },
        )
    except BaseException as error:
        atomic(
            args.output / "FAILED.json",
            {
                "error": repr(error),
                "pairs": completed,
                "requests": requests,
                "last_command": last_command,
                "partial": partial,
                "unix": time.time(),
                "full_acceptance": False,
            },
        )
        raise
    finally:
        if native is not None:
            if not closed:
                native.close()
            (args.output / "native-stderr.log").write_bytes(native.stderr)


if __name__ == "__main__":
    main()
