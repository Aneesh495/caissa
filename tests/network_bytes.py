"""Native batch parity and rehashed format controls for the independent reader."""

import argparse
import hashlib
import json
import random
import struct
import subprocess
import zlib
from pathlib import Path

import chess
import numpy as np

from verification.classical import evaluate
from verification.network_bytes import QuantizedNetwork, feature_indices


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--engine", required=True, type=Path)
    parser.add_argument("--network", required=True, type=Path, action="append")
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    randomizer = random.Random(982451867)
    board = chess.Board()
    fens = []
    for _ in range(1024):
        if board.is_game_over() or board.ply() > 180:
            board = chess.Board()
        fens.append(board.fen(en_passant="fen"))
        board.push(randomizer.choice(list(board.legal_moves)))
    features = np.stack([feature_indices(fen) for fen in fens])
    baselines = np.array([evaluate(fen) for fen in fens], dtype=np.int64)
    comparisons = 0
    with (args.output / "observations.jsonl").open("x") as stream:
        for path in args.network:
            interpreter = QuantizedNetwork(path)
            expected = interpreter.evaluate_features(features, baselines)
            native = subprocess.run(
                [str(args.engine.resolve()), "--net-probe", str(path)],
                input="\n".join(fens) + "\n",
                capture_output=True,
                text=True,
                check=True,
                timeout=30,
            )
            rows = [json.loads(line) for line in native.stdout.splitlines()]
            if len(rows) != len(fens):
                raise ValueError("native numerical work is missing")
            for index, (fen, row) in enumerate(zip(fens, rows)):
                if row["native"] != row["scalar"] or row["native"] != int(
                    expected[index]
                ):
                    raise ValueError(
                        "cached independent batch inference differs from native"
                    )
                if index % 127 == 0 and interpreter.infer(fen) != row["native"]:
                    raise ValueError(
                        "cached single and batch feature perspectives differ"
                    )
                stream.write(
                    json.dumps(
                        {
                            "network": path.name,
                            "fen": fen,
                            **row,
                            "independent_integer": int(expected[index]),
                        }
                    )
                    + "\n"
                )
                comparisons += 1
    raw = bytearray(args.network[-1].read_bytes())
    controls = []
    for name in [
        "truncation",
        "extra-bytes",
        "checksum",
        "identity",
        "baseline-contract",
        "feature-version",
        "architecture",
        "bias-overflow",
    ]:
        changed = bytearray(raw)
        if name == "truncation":
            del changed[-1]
        elif name == "extra-bytes":
            changed.extend(b"x")
        elif name == "checksum":
            changed[-1] ^= 1
        elif name == "identity":
            changed[40] = ord("z")
        elif name == "baseline-contract":
            struct.pack_into("<I", changed, 116, 2)
        elif name == "feature-version":
            struct.pack_into("<I", changed, 12, 2)
        elif name == "architecture":
            struct.pack_into("<I", changed, 20, 96)
        else:
            struct.pack_into("<i", changed, len(changed) - 4, (1 << 28) + 1)
            struct.pack_into("<I", changed, 112, zlib.crc32(changed[120:]))
        path = args.output / (name + ".cai")
        path.write_bytes(changed)
        try:
            QuantizedNetwork(path)
        except ValueError as error:
            controls.append({"control": name, "reason": str(error)})
        else:
            raise ValueError("independent network parser accepted " + name)
    summary = {
        "status": "passed",
        "profile": "diagnostic cached byte interpretation",
        "seed": 982451867,
        "native_integer_comparisons": comparisons,
        "format_rejections": controls,
        "engine_sha256": hashlib.sha256(args.engine.read_bytes()).hexdigest(),
        "networks": {
            str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in args.network
        },
        "full_acceptance": False,
    }
    (args.output / "SUMMARY.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary))


if __name__ == "__main__":
    main()
