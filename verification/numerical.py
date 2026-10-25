"""Independent saved-model floating/integer audit with bounded native replay.

No training implementation is imported. Verification reads the frozen probes,
replays their legal walk, interprets saved bytes and evaluates checkpoint tensors
with a separate float64 graph. It never trains or replaces missing observations.
"""

import argparse
import contextlib
import hashlib
import json
import math
import os
import random
import resource
import signal
import subprocess
import tempfile
import time
from pathlib import Path

import chess
import numpy as np
import torch

from verification.classical import evaluate as classical
from verification.learning import architecture, checkpoint, verify_export
from verification.network_bytes import QuantizedNetwork, feature_indices
from verification.protocol import read_json


class NumericalFailure(ValueError):
    """A fully replayed observation failed its frozen numerical endpoint."""

    def __init__(self, reason, observed):
        super().__init__(reason)
        self.observed = observed


def require(condition, reason):
    if not condition:
        raise ValueError(reason)


def sha(path):
    result = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(block)
    return result.hexdigest()


def close(left, right, reason, tolerance=1e-8):
    require(
        type(left) in [int, float]
        and math.isfinite(left)
        and abs(left - right) <= tolerance,
        reason,
    )


def distribution(values):
    ordered = sorted(values)
    point = 0.99 * (len(ordered) - 1)
    lower = math.floor(point)
    upper = math.ceil(point)
    percentile = ordered[lower] + (ordered[upper] - ordered[lower]) * (point - lower)
    return {
        "mean": math.fsum(ordered) / len(ordered),
        "p99": percentile,
        "max": ordered[-1],
    }


@contextlib.contextmanager
def replay_native(engine, network, positions):
    """Own one original CLI process; bound time, output files and cleanup."""
    with (
        positions.open("rb") as source,
        tempfile.TemporaryFile() as output,
        tempfile.TemporaryFile() as errors,
    ):
        start = time.monotonic()
        wall = time.time()
        before = resource.getrusage(resource.RUSAGE_CHILDREN)
        process = subprocess.Popen(
            [str(engine.resolve()), "--net-probe", str(network.resolve())],
            stdin=source,
            stdout=output,
            stderr=errors,
            start_new_session=True,
        )
        try:
            while process.poll() is None:
                require(
                    time.monotonic() - start < 120 and time.time() - wall < 120,
                    "saved native numerical replay deadline",
                )
                require(
                    os.fstat(output.fileno()).st_size <= 128 * 1024 * 1024
                    and os.fstat(errors.fileno()).st_size <= 1024 * 1024,
                    "saved native numerical replay output ceiling",
                )
                time.sleep(0.02)
            require(
                process.wait(timeout=2) == 0, "saved native numerical replay failed"
            )
            require(
                os.fstat(output.fileno()).st_size <= 128 * 1024 * 1024,
                "saved native numerical replay output ceiling",
            )
            after = resource.getrusage(resource.RUSAGE_CHILDREN)
            output.seek(0)
            yield output, {
                "exit": process.returncode,
                "seconds": time.monotonic() - start,
                "reaped_child_cpu_seconds": after.ru_utime
                + after.ru_stime
                - before.ru_utime
                - before.ru_stime,
            }
        finally:
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGTERM)
                try:
                    process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait(timeout=3)


def floating(parameters, indices, baseline, version):
    """Float64 operations on the exact saved float32 parameter values."""
    clip = 127 / 64 if version == 1 else 2047 / 1024
    with torch.inference_mode():
        x = torch.from_numpy(indices)
        hidden = (
            parameters["embedding.weight"][x].sum(dim=2) + parameters["bias0"]
        ).clamp(0, clip)
        hidden = hidden.reshape(len(indices), -1)
        for name in ["dense1", "dense2", "output"]:
            hidden = (
                hidden @ parameters[name + ".weight"].T + parameters[name + ".bias"]
            )
            if name != "output":
                hidden = torch.clamp(hidden, 0, clip)
        values = hidden[:, 0].numpy() * 400
        return values + baseline if version == 3 else values


def verify(
    root,
    engine,
    network_path,
    checkpoint_path,
    protocol=None,
    full=False,
    expected_network=None,
    expected_checkpoint=None,
    maximum_seconds=900,
):
    start = time.monotonic()
    wall = time.time()
    require(
        1 <= maximum_seconds <= 3600, "numerical verification duration outside bounds"
    )
    config = read_json((root / "CONFIG.json").read_text())
    summary = read_json((root / "SUMMARY.json").read_text())
    require(
        config["schema"] == "caissa-network-audit-v2" and config["trained"] is True,
        "trained numerical observation schema missing",
    )
    require(
        config["error_contract"] == "unclamped-quantization-and-clamped-inference",
        "numerical output/error contract differs",
    )
    count = config["probes"]
    seed = config["probe_seed"]
    tolerance = config["maximum_error_cp"]
    require(
        type(count) is int and 1 <= count <= 1000000 and type(seed) is int,
        "invalid numerical sample",
    )
    require(
        type(tolerance) in [int, float]
        and math.isfinite(tolerance)
        and 0 < tolerance <= 1000,
        "numerical error bound is absent or nonfinite",
    )
    require(
        type(config["maximum_seconds"]) in [int, float]
        and math.isfinite(config["maximum_seconds"])
        and 1 <= config["maximum_seconds"] <= 3600,
        "declared numerical duration outside bounds",
    )
    require(
        summary["frozen_maximum_error_cp"] == tolerance
        and summary["status"]
        in {"passed-frozen-error-bound", "failed-frozen-error-bound"},
        "saved numerical endpoint/status contradicts its frozen contract",
    )
    identities = {
        "engine_sha256": sha(engine),
        "network_sha256": sha(network_path),
        "checkpoint_sha256": sha(checkpoint_path),
    }
    require(
        all(config[key] == value for key, value in identities.items()),
        "numerical input identity differs",
    )
    require(
        expected_network is None or identities["network_sha256"] == expected_network,
        "network differs from external frozen identity",
    )
    require(
        expected_checkpoint is None
        or identities["checkpoint_sha256"] == expected_checkpoint,
        "checkpoint differs from external frozen identity",
    )
    network = QuantizedNetwork(network_path)
    state = checkpoint(checkpoint_path)
    version, width = architecture(state["config"], state["model"])
    wire_format = config.get("export_format", version)
    if wire_format != version:
        require(
            type(wire_format) is int
            and wire_format == 4
            and version == 3
            and config.get("export_contract")
            == "v3-float-to-v4-q4096-same-activation-ceiling-v1",
            "numerical conversion changed trained float semantics",
        )
    verify_export(
        network_path, state, identities["checkpoint_sha256"], export_format=wire_format
    )
    require(
        (network.version, network.width) == (wire_format, width),
        "saved numerical architecture differs",
    )
    if full:
        require(
            protocol is not None
            and expected_network is not None
            and expected_checkpoint is not None,
            "full numerical verification requires a frozen protocol and external model identities",
        )
        rule = read_json(Path(protocol).read_text())["network"]
        require(
            count >= 100000 and count == rule["probes"] and seed == rule["probe_seed"],
            "full frozen numerical sample or seed differs",
        )
        require(
            tolerance == rule["maximum_float_error_cp"] and tolerance <= 32,
            "full numerical endpoint was weakened",
        )
        require(
            (wire_format, width) == (rule["format"], rule["width"]),
            "full numerical architecture differs",
        )
        if wire_format == 4:
            require(
                rule.get("training_format") == 3
                and rule.get("export_contract") == config.get("export_contract")
                and rule.get("scale") == 4096
                and rule.get("clip") == 8188,
                "full precision conversion contract differs",
            )
        require(
            rule.get("error_contract") == config["error_contract"],
            "full numerical clamp/precision endpoints differ",
        )
        for key in ["total_seconds", "wall_seconds"]:
            require(
                type(summary.get(key)) in [int, float]
                and math.isfinite(summary[key])
                and 0 <= summary[key] <= config["maximum_seconds"],
                "full numerical campaign timing is missing or exceeded",
            )
    positions = root / "POSITIONS.fen"
    observations = root / "probes.jsonl"
    require(
        not positions.is_symlink() and not observations.is_symlink(),
        "symlinked numerical observations",
    )
    require(
        0 < positions.stat().st_size <= 256 * 1024 * 1024
        and 0 < observations.stat().st_size <= 512 * 1024 * 1024,
        "numerical observation byte ceiling",
    )
    require(
        sha(positions) == config["positions_sha256"] == summary["positions_sha256"],
        "frozen numerical positions changed",
    )
    require(
        sha(observations) == summary["probes_sha256"], "numerical observations changed"
    )
    require(
        config["generator"]
        == "standard-legal-walk-v1; terminal-or-ply>240-or-random<0.01 reset",
        "numerical input selection policy differs",
    )
    parameters = {
        name: value.to(torch.float64) for name, value in state["model"].items()
    }
    del state
    rng = random.Random(seed)
    board = chess.Board()
    errors = []
    raw_errors = []
    double_errors = []
    double_raw_errors = []
    clipped = 0
    float_discrepancy = 0.0
    processed = 0
    unique = set()
    with (
        replay_native(engine, network_path, positions) as (native, receipt),
        positions.open() as probes,
        observations.open() as saved,
    ):
        while processed < count:
            require(
                time.monotonic() - start < maximum_seconds
                and time.time() - wall < maximum_seconds,
                "cumulative numerical verification deadline",
            )
            batch = []
            rows = []
            replayed = []
            for _ in range(min(512, count - processed)):
                line = probes.readline(258)
                require(
                    line.endswith("\n") and len(line) <= 257,
                    "missing or oversized frozen probe",
                )
                fen = line.rstrip("\n")
                # Reconstruct the frozen legal walk independently of producer
                # helpers. This is input replay, never model/target selection.
                if (
                    board.outcome(claim_draw=False) is not None
                    or board.ply() > 240
                    or rng.random() < 0.01
                ):
                    board = chess.Board()
                require(
                    fen == board.fen(en_passant="fen"),
                    "probe differs from frozen seeded legal walk",
                )
                moves = list(board.generate_legal_moves())
                if moves:
                    board.push(moves[rng.randrange(len(moves))])
                raw = saved.readline(2049)
                require(
                    raw.endswith("\n") and len(raw) <= 2048,
                    "missing or oversized numerical observation",
                )
                row = read_json(raw)
                require(
                    set(row)
                    == {
                        "fen",
                        "scalar",
                        "native",
                        "reference",
                        "float",
                        "float_raw",
                        "reference_raw",
                        "error_cp",
                        "raw_error_cp",
                    }
                    and row["fen"] == fen,
                    "numerical observation order or fields differ",
                )
                raw_native = native.readline(2049)
                require(
                    raw_native.endswith(b"\n") and len(raw_native) <= 2048,
                    "native probe replay missing or oversized",
                )
                batch.append(fen)
                rows.append(row)
                replayed.append(read_json(raw_native.decode()))
                unique.add(fen)
            indices = np.stack([feature_indices(fen) for fen in batch])
            baseline = (
                np.array([classical(fen) for fen in batch], dtype=np.int64)
                if version == 3
                else None
            )
            raw_expected = network.evaluate_features(
                indices, baseline, clip_output=False
            )
            expected = raw_expected.clip(-29871, 29871)
            fp64 = floating(parameters, indices, baseline, version)
            for row, current, integer, raw_integer, flt in zip(
                rows, replayed, expected, raw_expected, fp64
            ):
                for key in ["scalar", "native", "reference", "reference_raw"]:
                    require(type(row[key]) is int, "noninteger numerical observation")
                require(
                    row["scalar"] == row["native"] == row["reference"] == int(integer),
                    "independent saved-byte integer inference differs",
                )
                require(
                    type(current["scalar"]) is int
                    and type(current["native"]) is int
                    and current["scalar"] == current["native"] == int(integer),
                    "exact saved native replay differs from independent integer inference",
                )
                require(
                    row["reference_raw"] == int(raw_integer),
                    "independent unclamped quantized inference differs",
                )
                close(
                    row["float_raw"],
                    float(flt),
                    "independent saved-parameter floating inference differs",
                    0.01,
                )
                clipped_float = max(-29871.0, min(29871.0, row["float_raw"]))
                close(row["float"], clipped_float, "floating inference clamp differs")
                error = abs(row["float"] - int(integer))
                raw_error = abs(row["float_raw"] - int(raw_integer))
                close(row["error_cp"], error, "saved numerical error differs")
                close(
                    row["raw_error_cp"],
                    raw_error,
                    "saved unclamped quantization error differs",
                )
                errors.append(error)
                raw_errors.append(raw_error)
                double_errors.append(
                    abs(max(-29871.0, min(29871.0, float(flt))) - int(integer))
                )
                double_raw_errors.append(abs(float(flt) - int(raw_integer)))
                float_discrepancy = max(
                    float_discrepancy, abs(float(flt) - row["float_raw"])
                )
                clipped += int(
                    row["float_raw"] != row["float"] or int(raw_integer) != int(integer)
                )
            processed += len(batch)
        require(
            not probes.read(1) and not saved.read(1) and not native.read(1),
            "extra numerical work beyond frozen sample",
        )
    require(
        summary["probes"] == processed
        and summary["probe_seed"] == seed
        and summary["trained"] is True,
        "numerical summary counts or seed differ",
    )
    for key in ["engine_sha256", "network_sha256", "checkpoint_sha256"]:
        require(
            summary[key] == identities[key]
            and sha(
                {
                    "engine_sha256": engine,
                    "network_sha256": network_path,
                    "checkpoint_sha256": checkpoint_path,
                }[key]
            )
            == identities[key],
            "numerical input changed during verification",
        )
    for key, values in [
        ("float_quantized_cp", errors),
        ("raw_float_quantized_cp", raw_errors),
    ]:
        for endpoint, value in distribution(values).items():
            close(
                summary[key][endpoint],
                value,
                "independent numerical summary differs: " + key + "." + endpoint,
            )
    require(
        summary["output_clipped_probes"] == clipped
        and summary["error_contract"] == config["error_contract"],
        "numerical clipping accounting differs",
    )
    producer_failed = max(max(errors), max(raw_errors)) > tolerance
    require(
        summary["status"]
        == (
            "failed-frozen-error-bound"
            if producer_failed
            else "passed-frozen-error-bound"
        ),
        "saved numerical endpoint status differs from independently computed errors",
    )
    failed = (
        max(max(errors), max(raw_errors), max(double_errors), max(double_raw_errors))
        > tolerance
    )
    result = {
        "status": "passed",
        "scope": (
            "full G06 numerical probe sample"
            if full
            else "diagnostic independent numerical replay"
        ),
        "probes": processed,
        "unique_fens": len(unique),
        "float_quantized_cp": distribution(errors),
        "raw_float_quantized_cp": distribution(raw_errors),
        "float64_quantized_cp": distribution(double_errors),
        "raw_float64_quantized_cp": distribution(double_raw_errors),
        "producer_float32_vs_independent_float64_max_cp": float_discrepancy,
        "output_clipped_probes": clipped,
        "native_replay": receipt,
        **identities,
        "maximum_error_cp": tolerance,
        "test_arrays_opened": False,
        "full_acceptance": False,
    }
    if failed:
        result["status"] = "failed-frozen-error-bound"
        raise NumericalFailure("frozen numerical error bound failed", result)
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("evidence", type=Path)
    parser.add_argument("--engine", required=True, type=Path)
    parser.add_argument("--network", required=True, type=Path)
    parser.add_argument("--checkpoint", required=True, type=Path)
    parser.add_argument("--protocol", type=Path)
    parser.add_argument("--expected-network-sha256")
    parser.add_argument("--expected-checkpoint-sha256")
    parser.add_argument("--require-full", action="store_true")
    parser.add_argument("--max-seconds", type=float, default=900)
    args = parser.parse_args()
    torch.set_num_threads(2)
    try:
        result = verify(
            args.evidence,
            args.engine,
            args.network,
            args.checkpoint,
            args.protocol,
            args.require_full,
            args.expected_network_sha256,
            args.expected_checkpoint_sha256,
            args.max_seconds,
        )
        print(json.dumps(result, allow_nan=False))
        return 0
    except NumericalFailure as error:
        print(
            json.dumps(
                {
                    "status": "rejected",
                    "reason": str(error),
                    "observed": error.observed,
                    "full_acceptance": False,
                },
                allow_nan=False,
            )
        )
        return 1
    except (
        ValueError,
        KeyError,
        TypeError,
        OSError,
        RuntimeError,
        subprocess.SubprocessError,
    ) as error:
        print(
            json.dumps(
                {"status": "rejected", "reason": str(error), "full_acceptance": False}
            )
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
