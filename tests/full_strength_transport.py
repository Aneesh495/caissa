"""Actual UCI configuration of every proposed full actor; no strength games."""

import argparse
import json
from pathlib import Path

import chess

from arena.client import UciClient
from tools.full_strength import configuration
from verification.acquisition import sha


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--engine", type=Path, required=True)
    parser.add_argument("--network", type=Path, required=True)
    parser.add_argument("--stockfish", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    rule = json.loads(Path("config/protocol-v3.proposed.json").read_text())
    if sha(args.stockfish) != rule["matches"]["stockfish_sha256"]:
        raise ValueError(
            "actual transport test external engine is not pinned Stockfish19"
        )
    args.output.mkdir(parents=True, exist_ok=False)
    rows = []
    for index in [None, 0, 1, 2]:
        setting = None if index is None else (index, args.stockfish.resolve())
        config = configuration(
            rule,
            args.engine.resolve(),
            args.network.resolve(),
            Path("config/strength-openings.json").resolve(),
            setting,
        )
        for role in ["candidate", "opponent"]:
            actor = config[role]
            with UciClient(
                actor["command"], actor["options"], warmup_nodes=1
            ) as client:
                move, elapsed, lines = client.play(chess.STARTING_FEN, [], nodes=1000)
                assert chess.Move.from_uci(move) in chess.Board().legal_moves
                rows.append(
                    {
                        "setting": index,
                        "role": role,
                        "actor": actor,
                        "executable_sha256": sha(Path(actor["command"][0])),
                        "bestmove": move,
                        "elapsed_ms": elapsed,
                        "actual_request": client.last_request,
                        "actual_uci": lines,
                        "handshake": client.handshake,
                        "configured_commands": client.configuration_commands,
                    }
                )
            (args.output / "observations.json").write_text(
                json.dumps(rows, indent=2) + "\n"
            )
    result = {
        "status": "passed",
        "actual_configured_actor_searches": len(rows),
        "network_sha256": sha(args.network),
        "scope": "Actual one-thousand-node transport probes with proposed full actor options; no full strength sample",
        "full_acceptance": False,
    }
    (args.output / "SUMMARY.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result))


if __name__ == "__main__":
    main()
