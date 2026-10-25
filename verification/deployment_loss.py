"""Recompute deployed integer losses on the already selected validation prefix.

Reads original array snapshots and wire weights, then checks every native score.
No training, checkpoint selection, calibration or test-array access occurs.
"""

import argparse
import hashlib
import json
import math
import time
from pathlib import Path

import chess
import numpy as np

from verification.classical import evaluate
from verification.network_bytes import QuantizedNetwork, feature_indices
from verification.protocol import read_json


def require(value, reason):
    if not value:
        raise ValueError(reason)


def sha(path):
    path = Path(path)
    require(
        0 < path.stat().st_size <= 32 * 1024 * 1024, "deployed-loss input byte ceiling"
    )
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1048576), b""):
            digest.update(block)
    return digest.hexdigest()


def board_from_row(row):
    board = chess.Board(None)
    for value in row[0]:
        index = int(value)
        if index == 12288:
            continue
        require(0 <= index < 12288, "validation feature index outside its contract")
        channel, square = divmod(index % 768, 64)
        require(
            board.piece_at(square) is None, "validation features duplicate a square"
        )
        board.set_piece_at(square, chess.Piece(channel % 6 + 1, channel < 6))
    board.turn = chess.WHITE
    require(board.is_valid(), "validation feature placement is not legal")
    require(
        np.array_equal(
            np.sort(row, axis=1), np.sort(feature_indices(board.fen()), axis=1)
        ),
        "validation feature perspectives disagree",
    )
    return board


def loss(scores, targets):
    logits = np.asarray(scores, dtype=np.float64) / 400
    values = np.logaddexp(0.0, logits) - targets * logits
    require(np.isfinite(values).all(), "nonfinite deployed validation loss")
    return float(math.fsum(map(float, values)) / len(values))


def check(args):
    from tools.heuristic_study import avoid_decisive_matches

    avoid_decisive_matches()
    from verification.numerical import replay_native

    started = time.time()
    deadline = min(started + 120, args.deadline_unix)
    require(
        sha(args.protocol) == args.expected_protocol_sha256,
        "deployed-loss profile differs from its external identity",
    )
    rule = read_json(args.protocol.read_text())
    require(
        rule["schema"] == "caissa-precision-followup-v1" and rule["status"] == "frozen",
        "deployment profile is not frozen",
    )
    spec = rule["validation"]
    require(
        spec["rows"] == 8192
        and spec["neural_weight"] == 10
        and spec["outcome_weight"] == 0.5
        and spec["minimum_loss_improvement_exclusive"] == 0
        and spec["selection_unchanged"] is True
        and spec["test_arrays_opened"] is False,
        "deployed-loss control or sample changed",
    )
    require(
        args.deadline_unix == rule["original_deadline_unix"] and time.time() < deadline,
        "original precision deadline differs or is exhausted",
    )
    require(
        sha(args.network) == spec["network_sha256"], "deployed-loss network changed"
    )
    record = args.slice / "SLICE.json"
    require(sha(record) == spec["slice_sha256"], "validation prefix identity changed")
    manifest = read_json(record.read_text())
    require(
        manifest["rows"] == 8192 and manifest["test_arrays_opened"] is False,
        "validation prefix scope changed",
    )
    for name, expected in manifest["files"].items():
        require(
            name
            in [
                "features.npy",
                "targets.npy",
                "baselines.npy",
                "identities.jsonl",
                "DATASET.json",
            ],
            "unexpected validation prefix filename",
        )
        require(
            0 < (args.slice / name).stat().st_size <= 16 * 1024 * 1024,
            "validation prefix file exceeds its byte ceiling",
        )
        require(
            name
            in [
                "features.npy",
                "targets.npy",
                "baselines.npy",
                "identities.jsonl",
                "DATASET.json",
            ]
            and sha(args.slice / name) == expected,
            "validation prefix file differs",
        )
    require(
        set(manifest["files"])
        == {
            "features.npy",
            "targets.npy",
            "baselines.npy",
            "identities.jsonl",
            "DATASET.json",
        },
        "validation prefix inventory differs",
    )
    require(
        sha(args.slice / "DATASET.json") == manifest["dataset_sha256"],
        "parent dataset identity differs",
    )
    source = read_json((args.slice / "DATASET.json").read_text())
    require(
        source["files"]["validation-features.npy"] == manifest["parent_feature_sha256"]
        and source["files"]["validation-targets.npy"]
        == manifest["parent_target_sha256"],
        "validation prefix parent identities differ",
    )
    x = np.load(args.slice / "features.npy", allow_pickle=False)
    y = np.load(args.slice / "targets.npy", allow_pickle=False)
    base = np.load(args.slice / "baselines.npy", allow_pickle=False)
    require(
        x.shape == (8192, 2, 32)
        and x.dtype == np.uint16
        and y.shape == (8192, 3)
        and y.dtype == np.float32
        and base.shape == (8192,)
        and base.dtype == np.int16,
        "validation prefix shape or numerical type differs",
    )
    require(
        np.isfinite(y).all() and np.all((y[:, [0, 2]] >= 0) & (y[:, [0, 2]] <= 1)),
        "validation targets are outside probability bounds",
    )
    identities = [
        read_json(line)
        for line in (args.slice / "identities.jsonl").read_text().splitlines()
    ]
    require(len(identities) == 8192, "validation identity sample is incomplete")
    fens, previous = [], ""
    for index, (row, identity) in enumerate(zip(x, identities)):
        if index % 128 == 0:
            require(time.time() < deadline, "deployed-loss deadline exhausted")
        board = board_from_row(row)
        actual = hashlib.sha256(board.board_fen().encode("ascii")).hexdigest()
        require(
            actual == identity["input_id"] and actual > previous,
            "validation identities do not match sorted normalized placements",
        )
        previous = actual
        fen = board.fen()
        require(
            evaluate(fen) == int(base[index]),
            "unchanged classical validation baseline differs",
        )
        fens.append(fen)
    network = QuantizedNetwork(args.network)
    require(
        (network.version, network.width, network.scale, network.clip)
        == (4, 64, 4096, 8188),
        "deployed validation numerical contract differs",
    )
    pure = network.evaluate_features(x[:4096], base[:4096])
    pure = np.concatenate([pure, network.evaluate_features(x[4096:], base[4096:])])
    numerator = pure * 10 + base.astype(np.int64) * 90
    mixed = np.where(numerator < 0, -((-numerator) // 100), numerator // 100)
    args.output.mkdir(parents=True, exist_ok=False)
    positions = args.output / "POSITIONS.fen"
    positions.write_text("\n".join(fens) + "\n")
    native_modes = {}
    for weight, expected_scores in [(100, pure), (0, base), (10, mixed)]:
        options = {"maximum_seconds": max(0.01, min(30, deadline - time.time()))}
        if weight != 100:
            options["neural_weight"] = weight
        with replay_native(args.engine, args.network, positions, **options) as (
            output,
            stats,
        ):
            raw = output.read(16 * 1024 * 1024 + 1)
        require(
            len(raw) <= 16 * 1024 * 1024,
            "native deployed validation output exceeds bounds",
        )
        (args.output / f"native-weight{weight}.stdout").write_bytes(raw)
        rows = [read_json(line) for line in raw.decode().splitlines()]
        require(len(rows) == 8192, "native deployed validation sample is incomplete")
        require(
            all(
                type(row["scalar"]) is int
                and type(row["native"]) is int
                and row["scalar"] == row["native"] == int(expected_scores[index])
                for index, row in enumerate(rows)
            ),
            "native deployed validation score differs",
        )
        native_modes[weight] = {"statistics": stats, "rows": rows}
    rows = native_modes[10]["rows"]
    targets = 0.5 * y[:, 0].astype(np.float64) + 0.5 * y[:, 2].astype(np.float64)
    with (args.output / "observations.jsonl").open("x") as stream:
        for index, row in enumerate(rows):
            require(
                type(row["scalar"]) is int
                and type(row["native"]) is int
                and row["scalar"] == row["native"] == int(mixed[index]),
                "deployed validation native/scalar/reference integer score differs",
            )
            stream.write(
                json.dumps(
                    {
                        "input_id": identities[index]["input_id"],
                        "fen": fens[index],
                        "target": float(targets[index]),
                        "baseline": int(base[index]),
                        "deployed_cp": int(mixed[index]),
                        "native": row,
                    }
                )
                + "\n"
            )
    untrained, trained = loss(base, targets), loss(mixed, targets)
    learning = read_json(
        Path("results/full-model-v3-2026-10-25/INDEPENDENT_LEARNING.json").read_text()
    )
    selected = next(
        row for row in learning["independent_seed_observations"] if row["seed"] == 73
    )
    require(
        learning["status"] == "passed"
        and learning["selected_seed"] == 73
        and learning["all_checkpoints_independently_evaluated"] == 240
        and abs(untrained - selected["independent_untrained_validation"]) < 0.00002,
        "deployed baseline differs from the original audited validation prefix",
    )
    result = {
        "status": (
            "passed" if trained < untrained else "failed-deployed-loss-improvement"
        ),
        "validation_rows": 8192,
        "untrained_loss": untrained,
        "deployed_loss": trained,
        "loss_improvement": untrained - trained,
        "neural_weight": 10,
        "actual_native_queries": len(rows) * 3,
        "native_modes": {
            str(weight): mode["statistics"] for weight, mode in native_modes.items()
        },
        "network_sha256": sha(args.network),
        "engine_sha256": sha(args.engine),
        "slice_sha256": sha(record),
        "protocol_sha256": sha(args.protocol),
        "observations_sha256": sha(args.output / "observations.jsonl"),
        "seconds": time.time() - started,
        "selection_changed": False,
        "test_arrays_opened": False,
        "full_acceptance": False,
        "scope": "Same original validation prefix used for selection, evaluated at deployed q4096 integer semantics. No model selection or population-strength inference.",
    }
    require(
        time.time() < deadline,
        "deployed-loss finalization exceeded its original deadline",
    )
    (args.output / "SUMMARY.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result))
    return 0 if trained < untrained else 2


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--engine", type=Path, required=True)
    parser.add_argument("--network", type=Path, required=True)
    parser.add_argument("--slice", type=Path, required=True)
    parser.add_argument("--protocol", type=Path, required=True)
    parser.add_argument("--expected-protocol-sha256", required=True)
    parser.add_argument("--deadline-unix", type=float, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return check(parser.parse_args())


if __name__ == "__main__":
    raise SystemExit(main())
