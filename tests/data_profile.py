"""Independent scalar checks of data-only distribution and target accounting."""

import argparse
import bisect
import json
import math
import random
from pathlib import Path

import chess
import numpy as np

from training.data_profile import (
    BINS,
    FEATURE_COUNT,
    empty_counts,
    observations,
    profile,
)
from training.features import features


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    generator = random.Random(104729)
    board = chess.Board()
    boards = []
    for i in range(160):
        if board.is_game_over() or i % 40 == 0:
            board = chess.Board()
        board.push(generator.choice(list(board.legal_moves)))
        boards.append(board.copy(stack=False))
    boards += [
        chess.Board("7k/8/8/8/8/8/4P3/4K3 w - - 0 1"),
        chess.Board("7k/8/8/8/8/8/8/4K3 w - - 0 1"),
    ]
    x = np.stack([features(b.fen(en_passant="fen")) for b in boards]).astype(np.uint16)
    y = np.array(
        [
            [
                generator.choice([0, 0.25, 0.5, 0.75, 1]),
                generator.choice([-32000, -2000, -101, 0, 99, 2000, 32000]),
                generator.choice([0, 0.1, 0.5, 0.9, 1]),
            ]
            for _ in boards
        ],
        dtype=np.float32,
    )
    actual, sums = observations(x, y)
    expected = {name: [0] * (len(edges) - 1) for name, edges in BINS.items()}
    weights = {chess.KNIGHT: 1, chess.BISHOP: 1, chess.ROOK: 2, chess.QUEEN: 4}
    for board, target in zip(boards, y):
        outcome, cp, probability = map(float, target)
        values = {
            "material": len(board.piece_map()),
            "phase": min(
                24,
                sum(weights.get(p.piece_type, 0) for p in board.piece_map().values()),
            ),
            "outcome": outcome,
            "teacher_cp": max(-2000, min(2000, cp)),
            "teacher_probability": probability,
            "absolute_target_disagreement": abs(outcome - probability),
        }
        for name, value in values.items():
            at = min(len(BINS[name]) - 2, bisect.bisect_right(BINS[name], value) - 1)
            assert at >= 0
            expected[name][at] += 1
    assert {name: value.tolist() for name, value in actual.items()} == expected
    assert sums["rows"] == len(boards)
    difference = [float(row[0]) - float(row[2]) for row in y]
    assert (
        abs(
            sums["sum_squared_target_disagreement"]
            - math.fsum(value * value for value in difference)
        )
        < 1e-12
    )
    merged = empty_counts()
    for begin in range(0, len(x), 7):
        count, _ = observations(x[begin : begin + 7], y[begin : begin + 7])
        for name in merged:
            merged[name] += count[name]
    assert all(np.array_equal(merged[name], actual[name]) for name in merged)
    rejected = []

    def invalid(label, bad_x, bad_y):
        try:
            observations(bad_x, bad_y)
        except ValueError as error:
            rejected.append({"case": label, "reason": str(error)})
        else:
            raise AssertionError("invalid profile input admitted: " + label)

    bad = x.copy()
    bad[0, 0, 0] = FEATURE_COUNT + 1
    invalid("out-of-range-feature", bad, y)
    for label, column, value in [
        ("nonfinite-target", 1, float("nan")),
        ("outcome-range", 0, 1.1),
        ("teacher-probability-range", 2, -0.01),
        ("unbounded-teacher", 1, 32001),
    ]:
        bad_y = y.copy()
        bad_y[0, column] = value
        invalid(label, x, bad_y)
    bad = x.copy()
    bad[0, 1, 0] = FEATURE_COUNT
    invalid("perspective-material", bad, y)
    bad = x[-2:-1].copy()
    pawn = np.flatnonzero((bad[0, 1] < FEATURE_COUNT) & (((bad[0, 1] // 64) % 6) == 0))[
        0
    ]
    bad[0, 1, pawn] += 4 * 64
    invalid("perspective-phase", bad, y[-2:-1])
    bad = x.copy()
    for perspective in (0, 1):
        king = np.flatnonzero(
            (bad[0, perspective] < FEATURE_COUNT)
            & (((bad[0, perspective] // 64) % 12) == 5)
        )[0]
        bad[0, perspective, king] = FEATURE_COUNT
    invalid("missing-king", bad, y)
    invalid("wrong-target-dtype", x, y.astype(np.float64))
    result = {
        "status": "passed",
        "independent_chess_feature_rows": len(boards),
        "chunk_size_independence": True,
        "controls": rejected,
        "model_evaluated": False,
        "full_acceptance": False,
    }
    if args.dataset is not None:
        if args.output is None:
            parser.error("--output is required with --dataset")
        observed = profile(args.dataset, args.output, maximum_seconds=60, chunk=257)
        result["real_dataset_rows"] = {
            name: value["rows"] for name, value in observed["splits"].items()
        }
    print(json.dumps(result))


if __name__ == "__main__":
    main()
