"""Enumerate every final-layer corner, then replay native score intervals.

No training implementation or native interval formula is imported. The affine
output reaches its extrema at corners of the 16-dimensional activation box.
Synthetic networks force both endpoints and exercise signed rounding, blending
and the mate clamp in all three wire formats.
"""

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
from verification.inference import infer


def rounded(value, divisor):
    magnitude = (abs(int(value)) + divisor // 2) // divisor
    return magnitude if value >= 0 else -magnitude


def divided(value, divisor):
    return value // divisor if value >= 0 else -((-value) // divisor)


def corners(path):
    raw = path.read_bytes()
    version, feature, count, width, h1, h2, scale, clip = struct.unpack_from(
        "<8I", raw, 8
    )
    assert raw[:8] == f"CAISSAN{version}".encode()
    assert (feature, count, width, h1, h2) == (1, 12288, 64, 32, 16)
    assert (version, scale, clip) in [(1, 64, 127), (2, 1024, 2047), (3, 1024, 2047)]
    length, crc, baseline = struct.unpack_from("<QII", raw, 104)
    assert length == len(raw) - 120 and crc == zlib.crc32(raw[120:])
    assert baseline == (1 if version == 3 else 0)
    weights = np.array(struct.unpack_from("<16h", raw, len(raw) - 36), dtype=np.int64)
    bias = struct.unpack_from("<i", raw, len(raw) - 4)[0]
    indices = np.arange(65536, dtype=np.int64)[:, None]
    activations = ((indices >> np.arange(16, dtype=np.int64)) & 1) * clip
    values = activations @ weights + bias
    return (
        version,
        rounded(values.min() * 400, scale * scale),
        rounded(values.max() * 400, scale * scale),
    )


def synthetic(template, path, version, endpoint, bias_sign):
    raw = bytearray(template)
    scale, clip = (64, 127) if version == 1 else (1024, 2047)
    raw[:8] = f"CAISSAN{version}".encode()
    struct.pack_into("<I", raw, 8, version)
    struct.pack_into("<II", raw, 32, scale, clip)
    struct.pack_into("<I", raw, 116, 1 if version == 3 else 0)
    raw[120:] = bytes(len(raw) - 120)
    weights = [-32768 if index % 2 else 32767 for index in range(16)]
    struct.pack_into("<16h", raw, len(raw) - 36, *weights)
    bias_limit = 1 << (20 if version == 1 else 28)
    struct.pack_into("<i", raw, len(raw) - 4, bias_sign * bias_limit)
    # Layer-two weights are zero. Its biases force exactly one corner, so the
    # lower/upper enclosure must be attained rather than merely include a score.
    for index, weight in enumerate(weights):
        active = (weight < 0) if endpoint == "lower" else (weight > 0)
        struct.pack_into(
            "<i", raw, len(raw) - 100 + index * 4, clip * scale if active else 0
        )
    struct.pack_into("<I", raw, 112, zlib.crc32(raw[120:]))
    path.write_bytes(raw)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--engine", required=True, type=Path)
    parser.add_argument("--network", required=True, type=Path, action="append")
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    rng = random.Random(49979687)
    board = chess.Board()
    fens = []
    for _ in range(256):
        if board.is_game_over() or board.ply() > 200:
            board = chess.Board()
        fens.append(board.fen(en_passant="fen"))
        board.push(rng.choice(list(board.legal_moves)))
    positions = "\n".join(fens) + "\n"
    (args.output / "positions.fen").write_text(positions)
    baseline = [evaluate(fen) for fen in fens]
    networks = [(path, None) for path in args.network]
    for version in [1, 2, 3]:
        for endpoint in ["lower", "upper"]:
            for bias_sign in [-1, 0, 1]:
                path = args.output / f"synthetic-v{version}-{endpoint}-{bias_sign}.cai"
                synthetic(
                    args.network[0].read_bytes(), path, version, endpoint, bias_sign
                )
                networks.append((path, endpoint))
    checks = 0
    with (args.output / "observations.jsonl").open("w") as log:
        for path, endpoint in networks:
            version, low, high = corners(path)
            exact = [infer(path, fen) for fen in fens[::16]]
            for weight in [0, 1, 10, 25, 50, 99, 100]:
                result = subprocess.run(
                    [str(args.engine.resolve()), "--net-probe", str(path), str(weight)],
                    input=positions,
                    capture_output=True,
                    text=True,
                    check=True,
                    timeout=20,
                )
                rows = [json.loads(line) for line in result.stdout.splitlines()]
                assert len(rows) == len(fens)
                for index, (fen, base, row) in enumerate(zip(fens, baseline, rows)):
                    enclosure = []
                    for value in [low, high]:
                        neural = max(
                            -29871, min(29871, value + (base if version == 3 else 0))
                        )
                        enclosure.append(
                            divided(neural * weight + base * (100 - weight), 100)
                        )
                    assert [row["lower"], row["upper"]] == enclosure
                    assert row["scalar"] == row["native"]
                    assert row["lower"] <= row["native"] <= row["upper"]
                    if endpoint:
                        assert (
                            row[endpoint] == row["native"]
                        ), "forced endpoint was not attained"
                    if index % 16 == 0:
                        expected = divided(
                            exact[index // 16] * weight + base * (100 - weight), 100
                        )
                        assert (
                            row["native"] == expected
                        ), "independent byte interpreter differs"
                    log.write(
                        json.dumps(
                            {"network": path.name, "weight": weight, "fen": fen, **row}
                        )
                        + "\n"
                    )
                    checks += 1
    summary = {
        "status": "passed",
        "profile": "diagnostic certified interval and exact inference",
        "corners_per_network": 65536,
        "networks": len(networks),
        "synthetic_forced_endpoint_networks": 18,
        "native_interval_comparisons": checks,
        "independent_integer_comparisons": len(networks) * 7 * 16,
        "seed": 49979687,
        "engine_sha256": hashlib.sha256(args.engine.read_bytes()).hexdigest(),
        "network_sha256": {
            path.name: hashlib.sha256(path.read_bytes()).hexdigest()
            for path, _ in networks
        },
        "observations_sha256": hashlib.sha256(
            (args.output / "observations.jsonl").read_bytes()
        ).hexdigest(),
        "full_acceptance": False,
    }
    (args.output / "SUMMARY.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary))


if __name__ == "__main__":
    main()
