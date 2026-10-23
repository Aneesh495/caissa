"""Compare real UCI history updates with the preceding search executable."""

import argparse
import hashlib
import json
import random
from pathlib import Path

import chess

from arena.client import UciClient


def answer(lines):
    infos = [line.split() for line in lines if line.startswith("info depth ")]
    result = {"bestmove": lines[-1].split()[1], "depth": 0, "score": None, "pv": []}
    if infos:
        fields = infos[-1]
        offset = fields.index("score")
        result.update(
            depth=int(fields[2]),
            score=fields[offset + 1 : offset + 3],
            pv=fields[fields.index("pv") + 1 :],
        )
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--previous", required=True)
    parser.add_argument("--engine", required=True)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    rng = random.Random(86028197)
    roots = [
        (chess.STARTING_FEN, False),
        ("4k3/8/8/5pP1/8/8/8/4K3 w - f6 0 1", False),
        ("4k3/8/8/8/8/8/8/6KR w H - 0 1", True),
        ("4k3/8/8/8/8/8/8/5KR1 w G - 0 1", True),
    ]
    cases = []
    history = []
    for number in range(64):
        if number % 16 == 0:
            root, variant = roots[number // 16]
            history = []
        if history and number % 5 == 0:
            history = history[: rng.randrange(len(history))]
        board = chess.Board(root, chess960=variant)
        for move in history:
            board.push_uci(move)
        for _ in range(2):
            moves = list(board.legal_moves)
            if not moves:
                history = []
                break
            move = rng.choice(moves)
            history.append(board.uci(move))
            board.push(move)
        cases.append((root, history.copy(), variant))
    for cycles in [1, 2, 3, 4]:
        cases.append(
            (chess.STARTING_FEN, ["g1f3", "g8f6", "f3g1", "f6g8"] * cycles, False)
        )
    for clock in [99, 149]:
        cases.append((f"7k/8/4K3/8/8/8/1P6/8 w - - {clock} 1", ["b2b3"], False))
    count = 0
    with (
        UciClient(
            [args.previous], {"Threads": 1, "Hash": 16}, warmup_nodes=1
        ) as previous,
        UciClient([args.engine], {"Threads": 1, "Hash": 16}, warmup_nodes=1) as current,
        (args.output / "observations.jsonl").open("x") as stream,
    ):
        for root, history, variant in cases:
            expected = chess.Board(root, chess960=variant)
            for move in history:
                expected.push_uci(move)
            observed = []
            raw = []
            for client in [previous, current]:
                client.send("setoption name UCI_Chess960 value " + str(variant).lower())
                client.send("isready")
                client.until("readyok", 5)
                _, _, lines = client.play(root, history, nodes=10000)
                response = answer(lines)
                if response["bestmove"] != "0000":
                    expected.parse_uci(response["bestmove"])
                elif not expected.is_game_over(claim_draw=False):
                    raise ValueError(
                        "history update produced a null move in a playable position"
                    )
                board = expected.copy(stack=True)
                for move in response["pv"]:
                    board.push_uci(move)
                observed.append(response)
                raw.append(lines)
            if observed[0] != observed[1]:
                raise ValueError(
                    "same full history changed fixed-node search after prefix reuse"
                )
            stream.write(
                json.dumps(
                    {
                        "root": root,
                        "moves": history,
                        "chess960": variant,
                        "expected_fen": expected.fen(en_passant="fen"),
                        "answers": observed,
                        "uci": raw,
                    }
                )
                + "\n"
            )
            stream.flush()
            count += 1
    summary = {
        "status": "passed",
        "profile": "diagnostic actual UCI full-history search parity",
        "positions": count,
        "nodes": 10000,
        "seed": 86028197,
        "engine_sha256": hashlib.sha256(Path(args.engine).read_bytes()).hexdigest(),
        "previous_sha256": hashlib.sha256(Path(args.previous).read_bytes()).hexdigest(),
        "observations_sha256": hashlib.sha256(
            (args.output / "observations.jsonl").read_bytes()
        ).hexdigest(),
        "full_acceptance": False,
    }
    (args.output / "SUMMARY.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary))


if __name__ == "__main__":
    main()
