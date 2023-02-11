"""Real exact-actor UCI readiness under a finite node-only nonrating probe."""

import argparse
import json
import subprocess
import time
from pathlib import Path

import chess

from arena.client import UciClient
from tools.campaign_process import atomic
from tools.heuristic_study import avoid_decisive_matches
from tools.strength_v4_profile import (
    configuration,
    frozen_profile,
    lineage,
    sha,
    ENGINE,
    NETWORK,
)
from verification.strength import principal_variations


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", type=Path, required=True)
    parser.add_argument("--expected-profile-sha256", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root = Path.cwd()
    avoid_decisive_matches()
    args.output.mkdir(parents=True, exist_ok=False)
    started = time.monotonic()
    wall = time.time()
    maximum = 180
    deadline = wall + maximum
    rule = frozen_profile(args.profile, args.expected_profile_sha256, root)
    engine = root / "build-search-semantics/caissa"
    network = root / "results/precision-v4-2026-10-25/selected-v4.cai"
    commit = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], text=True, timeout=5
    ).strip()
    derivation = lineage(
        root, root / "runs/searched-full-model-v3", engine, network, rule, commit
    )
    atomic(args.output / "DEPLOYMENT_LINEAGE.json", derivation)
    config = configuration(
        rule, engine, network, root / "config/strength-openings.json"
    )
    atomic(
        args.output / "CONFIG.json",
        {
            "source_commit": commit,
            "profile_sha256": args.expected_profile_sha256,
            "engine_sha256": ENGINE,
            "network_sha256": NETWORK,
            "nodes_per_query": 2000,
            "queries": 8,
            "maximum_seconds": maximum,
            "deadline_unix": deadline,
            "rating_experiment": False,
            "full_acceptance": False,
            "actors": {
                "candidate": config["candidate"],
                "opponent": config["opponent"],
            },
        },
    )
    cases = [
        ("start", chess.STARTING_FEN, []),
        (
            "opening",
            chess.STARTING_FEN,
            ["e2e4", "e7e5", "g1f3", "b8c6", "f1b5", "a7a6", "b5a4", "g8f6"],
        ),
        ("ep", "4k3/8/8/5pP1/8/8/8/4K3 w - f6 0 1", []),
        ("intended-claim", "1r5k/8/8/8/8/8/8/K7 w - - 99 50", []),
    ]
    observations = []
    try:
        for role in ["candidate", "opponent"]:
            actor = config[role]
            with UciClient(
                actor["command"], actor["options"], timeout=5, warmup_nodes=1
            ) as client:
                atomic(
                    args.output / (role + "-PREFLIGHT.json"),
                    {
                        "executable_sha256": sha(engine),
                        "options": actor["options"],
                        "configuration_commands": client.configuration_commands,
                        "declared_options": client.available_options,
                        "handshake": client.handshake,
                        "warmup_nodes": 1,
                        "warmup_ms": client.warmup_ms,
                    },
                )
                for name, fen, moves in cases:
                    if time.time() >= deadline or time.monotonic() - started >= maximum:
                        raise TimeoutError("v4 nonrating preflight ceiling exhausted")
                    board = chess.Board(fen)
                    for move in moves:
                        board.push_uci(move)
                    best, elapsed, lines = client.play(fen, moves, nodes=2000)
                    if chess.Move.from_uci(best) not in board.legal_moves:
                        raise ValueError(
                            "v4 actual actor returned an illegal preflight move"
                        )
                    principal_variations(board, lines)
                    infos = [line for line in lines if line.startswith("info depth ")]
                    for line in infos:
                        fields = line.split()
                        if int(fields[fields.index("nodes") + 1]) > 2000:
                            raise ValueError("v4 preflight exceeded its node limit")
                    if name == "intended-claim":
                        if (
                            not infos
                            or " score cp 0 " not in infos[-1]
                            or best != "a1a2"
                        ):
                            raise ValueError(
                                "v4 selected actor lost intended draw semantics"
                            )
                    row = {
                        "role": role,
                        "case": name,
                        "initial": fen,
                        "moves": moves,
                        "bestmove": best,
                        "elapsed_ms": elapsed,
                        "request": client.last_request,
                        "uci": lines,
                    }
                    observations.append(row)
                    atomic(
                        args.output / "PROGRESS.json",
                        {
                            "completed_queries": len(observations),
                            "required_queries": 8,
                            "last_case": name,
                        },
                    )
        atomic(
            args.output / "PREFLIGHT.json",
            {
                "status": "passed",
                "queries": len(observations),
                "observations": observations,
                "seconds": time.monotonic() - started,
                "maximum_seconds": maximum,
                "rating_experiment": False,
                "full_acceptance": False,
            },
        )
        print(
            json.dumps(
                {
                    "status": "passed",
                    "queries": len(observations),
                    "seconds": time.monotonic() - started,
                    "rating_experiment": False,
                    "full_acceptance": False,
                }
            )
        )
    except BaseException as error:
        atomic(
            args.output / "FAILED.json",
            {
                "reason": str(error),
                "observations": observations,
                "rating_experiment": False,
                "full_acceptance": False,
            },
        )
        raise


if __name__ == "__main__":
    main()
