"""Exercise nonzero residual inference and independently reconstructed baselines."""

import argparse, json, random, struct, subprocess, tempfile
from pathlib import Path
import chess
from verification.classical import evaluate
from verification.inference import infer


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--engine", default="build/caissa")
    parser.add_argument(
        "--network", type=Path, default=Path("models/diagnostic-v2.cai")
    )
    parser.add_argument("--probes", type=int, default=2000)
    args = parser.parse_args()
    raw = bytearray(args.network.read_bytes())
    assert raw[:8] == b"CAISSAN2"
    raw[:8] = b"CAISSAN3"
    struct.pack_into("<I", raw, 8, 3)
    struct.pack_into("<I", raw, 116, 1)
    Path("runs").mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="residual-contract-", dir="runs") as folder:
        network = Path(folder) / "nonzero-residual.cai"
        network.write_bytes(raw)
        native = subprocess.Popen(
            [args.engine, "--net-probe", str(network)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
        classical = subprocess.Popen(
            [args.engine, "--eval-probe"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
        board = chess.Board()
        rng = random.Random(1580030173)
        try:
            for _ in range(args.probes):
                if board.is_game_over() or board.ply() > 180:
                    board = chess.Board()
                fen = board.fen(en_passant="fen")
                classical.stdin.write(fen + "\n")
                classical.stdin.flush()
                baseline = json.loads(classical.stdout.readline())["classical"]
                assert baseline == evaluate(fen)
                native.stdin.write(fen + "\n")
                native.stdin.flush()
                result = json.loads(native.stdout.readline())
                reference = infer(network, fen)
                assert result["native"] == result["scalar"] == reference
                board.push(rng.choice(list(board.legal_moves)))
        finally:
            for child in [native, classical]:
                child.stdin.close()
                child.wait(timeout=5)
        wrong = Path(folder) / "wrong-baseline.cai"
        struct.pack_into("<I", raw, 116, 2)
        wrong.write_bytes(raw)
        result = subprocess.run(
            [args.engine, "--net-probe", str(wrong)],
            input="",
            capture_output=True,
            text=True,
            timeout=5,
        )
        assert result.returncode != 0 and "baseline contract" in result.stderr
    print(
        json.dumps(
            {
                "positions": args.probes,
                "nonzero_residual_scalar_native_reference": "bit-identical",
                "classical_board_oracle": "bit-identical",
                "wrong_baseline_contract": "rejected",
            }
        )
    )


if __name__ == "__main__":
    main()
