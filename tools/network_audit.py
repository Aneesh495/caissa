"""Cross-language feature/inference checks using held-out reachable probes."""

import argparse, hashlib, json, math, random, subprocess, time
from pathlib import Path
import chess
import numpy as np
import torch
from training.model import CaissaNet, features, integer_reference, export_network
from verification.learning import checkpoint


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--engine", default="build/caissa")
    ap.add_argument("--network", type=Path, required=True)
    ap.add_argument("--checkpoint", type=Path)
    ap.add_argument("--untrained-seed", type=int)
    ap.add_argument("--probes", type=int, default=100000)
    ap.add_argument("--seed", type=int, default=67867967)
    ap.add_argument("--maximum-error-cp", type=float)
    ap.add_argument("--max-seconds", type=float, default=900)
    ap.add_argument("--export-format", type=int, choices=[4])
    ap.add_argument("--output", type=Path, required=True)
    a = ap.parse_args()
    if not 1 <= a.probes <= 1000000 or not 1 <= a.max_seconds <= 3600:
        ap.error("probe count out of bounds")
    if a.maximum_error_cp is not None and (
        not math.isfinite(a.maximum_error_cp) or not 0 < a.maximum_error_cp <= 1000
    ):
        ap.error("finite positive numerical tolerance required")
    a.output.mkdir(parents=True, exist_ok=False)
    started = time.monotonic()
    wall_started = time.time()
    torch.set_num_threads(2)
    if a.checkpoint:
        state = checkpoint(a.checkpoint)
        model = CaissaNet(
            version=int(
                state["config"].get("network_contract", "v1").split("-")[0][1:]
            ),
            width=state["config"].get("width", 64),
        )
        model.load_state_dict(state["model"])
    elif a.untrained_seed is not None:
        torch.manual_seed(a.untrained_seed)
        wire_version = int.from_bytes(a.network.read_bytes()[8:12], "little")
        model = CaissaNet(
            version=3 if wire_version == 4 and a.export_format == 4 else wire_version
        )
    else:
        ap.error("provide saved checkpoint or explicitly labeled untrained seed")
    model.eval()
    wire_format = int.from_bytes(a.network.read_bytes()[8:12], "little")
    if a.export_format is None:
        if wire_format != model.version:
            raise ValueError("numerical audit needs an explicit precision conversion")
    elif model.version != 3 or wire_format != 4:
        raise ValueError("unsupported float-to-integer precision conversion")
    rng = random.Random(a.seed)
    b = chess.Board()
    fens = []
    for i in range(a.probes):
        if i % 1024 == 0 and (
            time.monotonic() - started > a.max_seconds
            or time.time() - wall_started > a.max_seconds
        ):
            raise TimeoutError("numerical campaign cumulative deadline")
        if b.is_game_over() or b.ply() > 240 or rng.random() < 0.01:
            b = chess.Board()
        fens.append(b.fen(en_passant="fen"))
        moves = list(b.legal_moves)
        if moves:
            b.push(rng.choice(moves))
    positions = a.output / "POSITIONS.fen"
    positions.write_text("\n".join(fens) + "\n")
    configuration = {
        "schema": "caissa-network-audit-v2",
        "probes": a.probes,
        "probe_seed": a.seed,
        "generator": "standard-legal-walk-v1; terminal-or-ply>240-or-random<0.01 reset",
        "engine_sha256": hashlib.sha256(Path(a.engine).read_bytes()).hexdigest(),
        "network_sha256": hashlib.sha256(a.network.read_bytes()).hexdigest(),
        "checkpoint_sha256": (
            hashlib.sha256(a.checkpoint.read_bytes()).hexdigest()
            if a.checkpoint
            else None
        ),
        "positions_sha256": hashlib.sha256(positions.read_bytes()).hexdigest(),
        "maximum_error_cp": a.maximum_error_cp,
        "maximum_seconds": a.max_seconds,
        "error_contract": "unclamped-quantization-and-clamped-inference",
        "trained": a.checkpoint is not None,
    }
    if a.export_format == 4:
        configuration.update(
            {
                "export_format": 4,
                "export_contract": "v3-float-to-v4-q4096-same-activation-ceiling-v1",
            }
        )
    (a.output / "CONFIG.json").write_text(json.dumps(configuration, indent=2) + "\n")
    p = subprocess.Popen(
        [a.engine, "--net-probe", str(a.network)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True,
        bufsize=1,
    )
    errors = []
    raw_errors = []
    clipped = 0
    start = time.monotonic()
    try:
        with (a.output / "probes.jsonl").open("w") as log, torch.inference_mode():
            for offset in range(0, len(fens), 512):
                if (
                    time.monotonic() - started > a.max_seconds
                    or time.time() - wall_started > a.max_seconds
                ):
                    raise TimeoutError("numerical campaign cumulative deadline")
                batch = fens[offset : offset + 512]
                x = np.stack([features(fen) for fen in batch])
                baseline = None
                if model.version == 3:
                    from verification.classical import evaluate

                    baseline = np.array(
                        [evaluate(fen) for fen in batch], dtype=np.int64
                    )
                raw_expected = integer_reference(
                    a.network, x, baseline, clip_output=False
                )
                expected = raw_expected.clip(-29871, 29871)
                floating = (
                    model(
                        torch.from_numpy(x),
                        baseline=(
                            torch.from_numpy(baseline) if baseline is not None else None
                        ),
                    ).numpy()
                    * 400
                )
                for fen, integer, raw_integer, flt in zip(
                    batch, expected, raw_expected, floating
                ):
                    p.stdin.write(fen + "\n")
                    p.stdin.flush()
                    line = p.stdout.readline(2049)
                    if not line or len(line) > 2048 or not line.endswith("\n"):
                        raise RuntimeError("native probe terminated")
                    native = json.loads(line)
                    if native["scalar"] != int(integer) or native["native"] != int(
                        integer
                    ):
                        raise ValueError("native/reference inference mismatch")
                    floating_output = max(-29871.0, min(29871.0, float(flt)))
                    error = abs(floating_output - int(integer))
                    raw_error = abs(float(flt) - int(raw_integer))
                    errors.append(error)
                    raw_errors.append(raw_error)
                    clipped += int(
                        float(flt) != floating_output
                        or int(raw_integer) != int(integer)
                    )
                    log.write(
                        json.dumps(
                            {
                                "fen": fen,
                                "scalar": native["scalar"],
                                "native": native["native"],
                                "reference": int(integer),
                                "float": floating_output,
                                "float_raw": float(flt),
                                "reference_raw": int(raw_integer),
                                "error_cp": error,
                                "raw_error_cp": raw_error,
                            }
                        )
                        + "\n"
                    )
                if offset % 10240 == 0:
                    print(f"{offset+len(batch)} probes complete", flush=True)
    finally:
        p.stdin.close()
        try:
            p.wait(timeout=5)
        except subprocess.TimeoutExpired:
            p.kill()
            p.wait(timeout=5)
            raise
        p.stdout.close()
    if p.returncode != 0:
        raise ValueError("native numerical probe failed")
    if (
        time.monotonic() - started > a.max_seconds
        or time.time() - wall_started > a.max_seconds
    ):
        raise TimeoutError("numerical campaign cumulative deadline")
    if (
        hashlib.sha256(Path(a.engine).read_bytes()).hexdigest()
        != configuration["engine_sha256"]
        or hashlib.sha256(a.network.read_bytes()).hexdigest()
        != configuration["network_sha256"]
        or (
            a.checkpoint
            and hashlib.sha256(a.checkpoint.read_bytes()).hexdigest()
            != configuration["checkpoint_sha256"]
        )
    ):
        raise ValueError("numerical campaign input bytes changed during execution")
    e = np.array(errors)
    raw_e = np.array(raw_errors)
    failed_bound = (
        a.maximum_error_cp is not None
        and max(e.max(), raw_e.max()) > a.maximum_error_cp
    )
    summary = {
        "status": (
            "failed-frozen-error-bound"
            if failed_bound
            else (
                "passed-frozen-error-bound"
                if a.maximum_error_cp is not None
                else "parity-passed-error-bound-not-yet-frozen"
            )
        ),
        "probes": len(errors),
        "probe_seed": a.seed,
        "frozen_maximum_error_cp": a.maximum_error_cp,
        "float_quantized_cp": {
            "mean": float(e.mean()),
            "p99": float(np.quantile(e, 0.99)),
            "max": float(e.max()),
        },
        "raw_float_quantized_cp": {
            "mean": float(raw_e.mean()),
            "p99": float(np.quantile(raw_e, 0.99)),
            "max": float(raw_e.max()),
        },
        "output_clipped_probes": clipped,
        "error_contract": configuration["error_contract"],
        "engine_sha256": configuration["engine_sha256"],
        "checkpoint_sha256": configuration["checkpoint_sha256"],
        "positions_sha256": configuration["positions_sha256"],
        "seconds": time.monotonic() - start,
        "total_seconds": time.monotonic() - started,
        "wall_seconds": time.time() - wall_started,
        "timing_scope": "seconds is inference only; total_seconds and wall_seconds include model loading and frozen probe construction",
        "network_sha256": hashlib.sha256(a.network.read_bytes()).hexdigest(),
        "trained": a.checkpoint is not None,
        "full_acceptance": False,
        "probes_sha256": hashlib.sha256(
            (a.output / "probes.jsonl").read_bytes()
        ).hexdigest(),
    }
    (a.output / "SUMMARY.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary))
    if failed_bound:
        raise ValueError("frozen float/integer error endpoint exceeded")


if __name__ == "__main__":
    main()
