"""Check explicit q4096 conversion without changing a trained float model."""

import argparse
import hashlib
import json
import random
import struct
import subprocess
import time
from pathlib import Path

import chess
import numpy as np
import torch

from training.model import CaissaNet, export_network, integer_reference, state_hash
from verification.classical import evaluate
from verification.learning import checkpoint, verify_export
from verification.network_bytes import QuantizedNetwork, feature_indices
from verification.verify import Rejection


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--engine", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    started = time.time()
    torch.set_num_threads(2)
    args.output.mkdir(parents=True, exist_ok=False)
    identity = hashlib.sha256(args.checkpoint.read_bytes()).hexdigest()
    assert (
        identity == "c76d8e9ef0f2255531bc9085f5d0330a7a4152cf9b21a65ff8aee740ab8b2005"
    )
    state = checkpoint(args.checkpoint)
    model = CaissaNet(version=3, width=64)
    model.load_state_dict(state["model"], strict=True)
    before = state_hash(model)
    old = args.output / "unchanged-v3.cai"
    new = args.output / "selected-v4.cai"
    export_network(model, old, identity)
    assert (
        hashlib.sha256(old.read_bytes()).hexdigest()
        == "c251670ec53ba38a680c16cc6199be48f89cc829dd5483197e6d4b39ac6debf6"
    )
    record = export_network(model, new, identity, export_format=4)
    assert state_hash(model) == before
    verify_export(old, state, identity)
    verify_export(new, state, identity, export_format=4)
    default_rejected = False
    try:
        verify_export(new, state, identity)
    except Rejection as error:
        assert "header differs" in str(error)
        default_rejected = True
    assert default_rejected, "the old contract must not silently accept a new format"
    export_network(model, args.output / "v3-after.cai", identity)
    assert old.read_bytes() == (args.output / "v3-after.cai").read_bytes()
    raw = new.read_bytes()
    assert struct.unpack_from("<II", raw, 32) == (4096, 8188)
    assert 8188 / 4096 == model.clip == 2047 / 1024
    randomizer, board, fens = random.Random(49979693), chess.Board(), []
    for _ in range(1024):
        if board.is_game_over() or board.ply() > 180:
            board = chess.Board()
        fens.append(board.fen(en_passant="fen"))
        board.push(randomizer.choice(list(board.legal_moves)))
    features = np.stack([feature_indices(fen) for fen in fens])
    baselines = np.array([evaluate(fen) for fen in fens], dtype=np.int64)
    independent = QuantizedNetwork(new).evaluate_features(features, baselines)
    assert np.array_equal(independent, integer_reference(new, features, baselines))
    native = subprocess.run(
        [str(args.engine.resolve()), "--net-probe", str(new)],
        input="\n".join(fens) + "\n",
        capture_output=True,
        text=True,
        check=True,
        timeout=30,
    )
    rows = [json.loads(line) for line in native.stdout.splitlines()]
    assert len(rows) == 1024
    for index, row in enumerate(rows):
        assert row["native"] == row["scalar"] == int(independent[index])
    controls = []
    for name, offset, value in [
        ("expanded-real-cap", 36, 8191),
        ("old-scale", 32, 1024),
        ("lost-baseline", 116, 0),
        ("magic-version", 8, 3),
    ]:
        damaged = bytearray(raw)
        struct.pack_into("<I", damaged, offset, value)
        path = args.output / (name + ".cai")
        path.write_bytes(damaged)
        try:
            QuantizedNetwork(path)
        except ValueError:
            pass
        else:
            raise AssertionError("independent precision reader admitted " + name)
        result = subprocess.run(
            [str(args.engine.resolve()), "--net-probe", str(path)],
            input="",
            capture_output=True,
            text=True,
            timeout=5,
        )
        assert result.returncode != 0
        controls.append(
            {"case": name, "exit": result.returncode, "stderr": result.stderr}
        )
    result = {
        "status": "passed",
        "original_float_parameters_unchanged": True,
        "legacy_export_byte_identical": True,
        "same_real_activation_ceiling": True,
        "actual_native_integer_comparisons": 1024,
        "negative_controls": controls,
        "network": record,
        "checkpoint_sha256": identity,
        "parameter_sha256": before,
        "seconds": time.time() - started,
        "full_acceptance": False,
    }
    (args.output / "SUMMARY.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result))


if __name__ == "__main__":
    main()
