"""Independently replay saved validation graphs and checkpoint selection.

This module never imports training, opens test arrays, or performs gradients.
It reads only bounded tensor checkpoints with an explicit safe type allowlist.
The full caller must also run the separate original-game/dataset verifier.
"""

import argparse
import hashlib
import json
import math
import pickle
import random
import re
import struct
import time
import zlib
from pathlib import Path

import chess
import numpy as np
import torch
from torch.torch_version import TorchVersion

from verification.classical import evaluate as classical
from verification.dataset import digest, feature_rows
from verification.verify import Rejection, load

FEATURE_COUNT = 12288
LOSS_TOLERANCE = 0.00002
MAX_CHECKPOINT_BYTES = 128 * 1024 * 1024
MAX_SAMPLER_VALUES = 100000000


def close(actual, expected, message, tolerance=LOSS_TOLERANCE):
    if not isinstance(actual, (int, float)) or not math.isfinite(actual):
        raise Rejection(message + ": nonfinite or missing value")
    if not isinstance(expected, (int, float)) or not math.isfinite(expected):
        raise Rejection(message + ": nonfinite reference")
    if abs(float(actual) - float(expected)) > tolerance:
        raise Rejection(message)


def finite(value):
    if isinstance(value, torch.Tensor):
        if not torch.isfinite(value).all():
            raise Rejection("nonfinite checkpoint tensor")
    elif isinstance(value, np.ndarray):
        if not np.isfinite(value).all():
            raise Rejection("nonfinite checkpoint RNG array")
    elif isinstance(value, float) and not math.isfinite(value):
        raise Rejection("nonfinite checkpoint scalar")
    elif isinstance(value, dict):
        for child in value.values():
            finite(child)
    elif isinstance(value, (tuple, list)):
        for child in value:
            finite(child)


def checkpoint(path):
    path = Path(path)
    if not path.is_file() or not 0 < path.stat().st_size <= MAX_CHECKPOINT_BYTES:
        raise Rejection("checkpoint is missing or exceeds its byte limit")
    # Earlier checkpoints recorded torch.__version__ as a TorchVersion string
    # subclass. No arbitrary classes, reducers or unrestricted pickle are used.
    allowed = [
        np._core.multiarray._reconstruct,
        np.ndarray,
        np.dtype,
        np.dtypes.UInt32DType,
        TorchVersion,
    ]
    try:
        with torch.serialization.safe_globals(allowed):
            state = torch.load(path, map_location="cpu", weights_only=True, mmap=True)
    except (pickle.UnpicklingError, RuntimeError, ValueError, EOFError) as error:
        raise Rejection("unsupported or corrupt bounded checkpoint") from error
    if not isinstance(state, dict):
        raise Rejection("checkpoint object is not a mapping")
    finite(state)
    return state


def parameter_hash(parameters):
    result = hashlib.sha256()
    for name, value in sorted(parameters.items()):
        result.update(name.encode())
        result.update(value.detach().cpu().numpy().tobytes())
    return result.hexdigest()


def architecture(config, parameters):
    contract = re.fullmatch(
        r"v([23])-q1024-clip2047-(32|64|128)-32-16", config["network_contract"]
    )
    if not contract:
        raise Rejection("unsupported learned numerical contract")
    version, width = map(int, contract.groups())
    shapes = {
        "bias0": (width,),
        "embedding.weight": (12289, width),
        "dense1.weight": (32, width * 2),
        "dense1.bias": (32,),
        "dense2.weight": (16, 32),
        "dense2.bias": (16,),
        "output.weight": (1, 16),
        "output.bias": (1,),
    }
    if set(parameters) != set(shapes):
        raise Rejection("checkpoint parameter inventory differs")
    for name, shape in shapes.items():
        value = parameters[name]
        if (
            not isinstance(value, torch.Tensor)
            or value.dtype != torch.float32
            or tuple(value.shape) != shape
        ):
            raise Rejection("checkpoint parameter shape/dtype differs: " + name)
    if torch.count_nonzero(parameters["embedding.weight"][-1]).item():
        raise Rejection("padding embedding contributes a learned feature")
    return version, width


def board_from_features(row):
    """Invert mover-normalized placement, then check both feature perspectives."""
    if row.dtype != np.uint16 or row.shape != (2, 32):
        raise Rejection("invalid sparse feature shape or precision")
    board = chess.Board(None)
    board.turn = chess.WHITE
    for value in row[0]:
        value = int(value)
        if value == FEATURE_COUNT:
            continue
        if not 0 <= value < FEATURE_COUNT:
            raise Rejection("feature index out of range")
        relative, square = divmod(value % 768, 64)
        if board.piece_at(square) is not None:
            raise Rejection("two sparse features occupy one square")
        board.set_piece_at(square, chess.Piece(relative % 6 + 1, relative < 6))
    if not board.is_valid() or not np.array_equal(
        np.sort(row, axis=1), feature_rows(board)
    ):
        raise Rejection("sparse perspectives do not encode the same legal placement")
    return board


def validation_loss(
    parameters, source_x, source_y, count, outcome_weight, quantized, baseline=None
):
    """A separate tensor graph using saved arrays, without the model class."""
    total = 0.0
    scale = 1024
    ceiling = 2047 / scale
    with torch.inference_mode():
        embedding = parameters["embedding.weight"]
        bias = parameters["bias0"]
        if quantized:
            embedding = torch.round(embedding * scale) / scale
            bias = torch.round(bias * scale) / scale
        for start in range(0, count, 512):
            stop = min(start + 512, count)
            indices = torch.from_numpy(np.array(source_x[start:stop], dtype=np.int64))
            labels = torch.from_numpy(np.array(source_y[start:stop], dtype=np.float32))
            activations = embedding[indices].sum(dim=2) + bias
            activations = torch.clamp(activations, 0, ceiling)
            if quantized:
                activations = torch.round(activations * scale) / scale
            activations = activations.reshape(stop - start, -1)
            for layer in ["dense1", "dense2", "output"]:
                weights = parameters[layer + ".weight"]
                biases = parameters[layer + ".bias"]
                if quantized:
                    weights = torch.round(weights * scale) / scale
                    biases = torch.round(biases * scale * scale) / (scale * scale)
                activations = activations @ weights.T + biases
                if layer != "output":
                    activations = torch.clamp(activations, 0, ceiling)
                    if quantized:
                        activations = torch.round(activations * scale) / scale
            logits = activations.reshape(-1)
            if baseline is not None:
                logits = (
                    logits
                    + torch.from_numpy(np.array(baseline[start:stop], dtype=np.float32))
                    / 400
                )
            probabilities = (
                labels[:, 2]
                if labels.shape[1] == 3
                else torch.sigmoid(labels[:, 1] / 400)
            )
            targets = (
                outcome_weight * labels[:, 0] + (1 - outcome_weight) * probabilities
            )
            # Stable BCE written independently from the trainer's loss call.
            values = (
                torch.clamp(logits, min=0)
                - logits * targets
                + torch.log1p(torch.exp(-torch.abs(logits)))
            )
            if not torch.isfinite(values).all():
                raise Rejection("nonfinite independent validation inference")
            total += float(values.sum())
    return total / count


def verify_optimizer(state, config):
    step = state["step"]
    if state["updates"] != step or not 1 <= step <= config["steps"]:
        raise Rejection("checkpoint lacks the declared real update count")
    optimizer = state["optimizer"]
    if len(optimizer["param_groups"]) != 1:
        raise Rejection("optimizer parameter groups differ")
    group = optimizer["param_groups"][0]
    parameters = list(state["model"].values())
    if group["params"] != list(range(len(parameters))) or set(
        optimizer["state"]
    ) != set(group["params"]):
        raise Rejection("optimizer state does not cover every model parameter")
    for index, parameter in enumerate(parameters):
        saved = optimizer["state"][index]
        if (
            set(saved) != {"step", "exp_avg", "exp_avg_sq"}
            or float(saved["step"]) != step
        ):
            raise Rejection("optimizer step provenance differs")
        for key in ["exp_avg", "exp_avg_sq"]:
            if (
                saved[key].shape != parameter.shape
                or saved[key].dtype != parameter.dtype
            ):
                raise Rejection("optimizer moment shape/precision differs")
        if torch.any(saved["exp_avg_sq"] < 0):
            raise Rejection("optimizer second moment is negative")
    if not any(
        torch.count_nonzero(value["exp_avg"]).item()
        for value in optimizer["state"].values()
    ):
        raise Rejection("optimizer has no gradient moment evidence")
    schedule = state["scheduler"]
    if (
        schedule["last_epoch"] != step
        or schedule["T_max"] != config["steps"]
        or schedule["_step_count"] != step + 1
    ):
        raise Rejection("scheduler position differs from real updates")
    expected = config["lr"] * (
        0.05 + 0.95 * (1 + math.cos(math.pi * step / config["steps"])) / 2
    )
    close(group["lr"], expected, "optimizer cosine learning rate differs", 1e-10)
    close(schedule["_last_lr"][0], expected, "scheduler learning rate differs", 1e-10)
    close(group["weight_decay"], 0.00001, "optimizer weight decay differs", 0)
    close(schedule["eta_min"], config["lr"] * 0.05, "scheduler floor differs", 1e-12)
    generator = torch.Generator()
    generator.set_state(state["torch_rng"])
    python_rng = random.Random()
    python_rng.setstate(state["python_rng"])
    numpy_rng = np.random.RandomState()
    numpy_rng.set_state(state["numpy_rng"])


def sampler_states(seed, steps, batch, positions):
    if max(steps) * batch > MAX_SAMPLER_VALUES:
        raise Rejection("sampler replay exceeds the declared verification work limit")
    sampler = np.random.default_rng(seed ^ 0x13579)
    current = 0
    for step in sorted(set(steps)):
        remaining = (step - current) * batch
        while remaining:
            n = min(remaining, 1048576)
            sampler.integers(0, positions, size=n)
            remaining -= n
        current = step
        yield step, sampler.bit_generator.state


def verify_export(path, state, identity):
    raw = Path(path).read_bytes()
    version, width = architecture(state["config"], state["model"])
    if len(raw) < 120 or raw[:8] != f"CAISSAN{version}".encode():
        raise Rejection("selected network header differs")
    if struct.unpack("<8I", raw[8:40]) != (
        version,
        1,
        12288,
        width,
        32,
        16,
        1024,
        2047,
    ):
        raise Rejection("selected network dimensions or precision differ")
    if raw[40:104].decode("ascii") != identity:
        raise Rejection("selected export does not name the selected checkpoint")
    length, crc, baseline = struct.unpack("<QII", raw[104:120])
    if (
        length != len(raw) - 120
        or crc != zlib.crc32(raw[120:])
        or baseline != (1 if version == 3 else 0)
    ):
        raise Rejection("selected export checksum or classical contract differs")
    offset = 120
    parameters = state["model"]
    entries = [("embedding.weight", 1024, "<i2"), ("bias0", 1024, "<i4")]
    entries += [
        (layer + suffix, scale, dtype)
        for layer in ["dense1", "dense2", "output"]
        for suffix, scale, dtype in [
            (".weight", 1024, "<i2"),
            (".bias", 1048576, "<i4"),
        ]
    ]
    for name, scale, dtype in entries:
        tensor = parameters[name].numpy()
        if name == "embedding.weight":
            tensor = tensor[:12288]
        rounded = np.rint(tensor.astype(np.float64) * scale)
        bound = 32767 if dtype == "<i2" else 1 << 28
        if np.abs(rounded).max(initial=0) > bound:
            raise Rejection("selected export exceeds its integer arithmetic contract")
        expected = rounded.astype(dtype).tobytes()
        if raw[offset : offset + len(expected)] != expected:
            raise Rejection(
                "selected export weights differ from independently quantized checkpoint"
            )
        offset += len(expected)
    if offset != len(raw):
        raise Rejection("selected export has unconsumed trailing bytes")


def baseline_arrays(
    folder, dataset, manifest, dataset_sha, required_count, samples, seed
):
    record = load(folder / "BASELINES.json")
    config = record["config"]
    if (
        config["dataset_sha256"] != dataset_sha
        or config["classical_contract"] != 1
        or record["test_accessed"] is not False
    ):
        raise Rejection("residual baseline provenance differs")
    if digest(folder / "caissa") != config["engine_sha256"]:
        raise Rejection("frozen original baseline executable differs")
    if set(record["files"]) != {"train-baseline.npy", "validation-baseline.npy"}:
        raise Rejection("residual baseline includes unexpected or test arrays")
    arrays = {}
    checked = 0
    for split in ["train", "validation"]:
        name = split + "-baseline.npy"
        if digest(folder / name) != record["files"][name]:
            raise Rejection("residual baseline bytes differ")
        values = np.load(folder / name, mmap_mode="r", allow_pickle=False)
        if values.dtype != np.int16 or values.shape != (manifest["splits"][split],):
            raise Rejection("residual baseline shape/precision differs")
        source = np.load(
            dataset / (split + "-features.npy"), mmap_mode="r", allow_pickle=False
        )
        indices = (
            np.arange(required_count)
            if split == "validation"
            else np.unique(
                np.random.default_rng(seed).integers(
                    len(source), size=min(samples, len(source))
                )
            )
        )
        for index in indices:
            board = board_from_features(source[int(index)])
            if classical(board.fen()) != int(values[index]):
                raise Rejection(
                    "residual baseline disagrees with independent classical evaluation"
                )
            checked += 1
        arrays[split] = values
    return arrays["validation"], digest(folder / "BASELINES.json"), checked


def verify_learning(
    dataset, runs, selection, baseline=None, protocol=None, require_full=False
):
    dataset, selection = Path(dataset), Path(selection)
    runs = [Path(path) for path in runs]
    if not 3 <= len(runs) <= 10 or len({p.resolve() for p in runs}) != len(runs):
        raise Rejection("three to ten distinct seed directories required")
    manifest = load(dataset / "DATASET.json")
    dataset_sha = digest(dataset / "DATASET.json")
    if require_full and (
        manifest["splits"]["train"] < 10000000
        or manifest["counts"]["completed_games"] < 100000
        or not manifest.get("functional_deduplication")
    ):
        raise Rejection("full original data floors are absent")
    rule = load(protocol) if protocol else None
    if require_full and rule is None:
        raise Rejection("full learning requires the prospectively frozen protocol")
    for name in ["validation-features.npy", "validation-targets.npy"]:
        if digest(dataset / name) != manifest["files"][name]:
            raise Rejection("validation input bytes differ")
    x = np.load(dataset / "validation-features.npy", mmap_mode="r", allow_pickle=False)
    y = np.load(dataset / "validation-targets.npy", mmap_mode="r", allow_pickle=False)
    if (
        x.shape != (manifest["splits"]["validation"], 2, 32)
        or x.dtype != np.uint16
        or y.shape not in [(len(x), 2), (len(x), 3)]
        or y.dtype != np.float32
    ):
        raise Rejection("validation tensor shape/precision differs")
    count = min(8192, len(x))
    if count < 1:
        raise Rejection("empty validation work")
    labels = y[:count]
    if (
        not np.isfinite(labels).all()
        or np.any((labels[:, 0] < 0) | (labels[:, 0] > 1))
        or (y.shape[1] == 3 and np.any((labels[:, 2] < 0) | (labels[:, 2] > 1)))
    ):
        raise Rejection("invalid validation targets")
    for row in x[:count]:
        board_from_features(row)
    selected_record = load(selection / "SELECTION.json")
    if (
        selected_record["dataset_sha256"] != dataset_sha
        or selected_record.get("test_accessed") is not False
    ):
        raise Rejection("selection dataset or test-access contract differs")
    origins = {}
    for row in selected_record["all_seeds"]:
        if (
            row["seed"] in origins
            or not isinstance(row.get("folder"), str)
            or not 0 < len(row["folder"]) <= 4096
            or any(char in row["folder"] for char in "\0\r\n")
        ):
            raise Rejection("invalid or duplicated selection origin metadata")
        origins[row["seed"]] = row["folder"]
    if len(origins) != len(runs):
        raise Rejection("selection seed inventory differs from supplied checkpoints")
    rows = []
    seeds = set()
    numerical = None
    baseline_values = None
    baseline_sha = None
    baseline_checked = 0
    seed_observations = []
    for folder in runs:
        config = load(folder / "CONFIG.json")
        if (
            config["dataset_sha256"] != dataset_sha
            or config["seed"] in seeds
            or config["seed"] not in origins
        ):
            raise Rejection("duplicate seed or mismatched training data")
        seeds.add(config["seed"])
        candidate_config = {
            key: value for key, value in config.items() if key != "seed"
        }
        if numerical is None:
            numerical = candidate_config
        elif numerical != candidate_config:
            raise Rejection("seed numerical settings or training budgets differ")
        if (
            config["validation_count"] != count
            or not 1 <= config["steps"] <= 1000000
            or not 1 <= config["checkpoint_every"] <= config["steps"]
            or not 0 <= config["outcome_weight"] <= 1
        ):
            raise Rejection("invalid declared learning work")
        if rule:
            for key in [
                "steps",
                "batch",
                "threads",
                "device",
                "lr",
                "outcome_weight",
                "checkpoint_every",
            ]:
                if config[key] != rule["training"][key]:
                    raise Rejection("training differs from frozen protocol: " + key)
            expected_contract = f"v{rule['network']['format']}-q1024-clip2047-{rule['network']['width']}-32-16"
            if config["network_contract"] != expected_contract:
                raise Rejection("architecture differs from frozen protocol")
        pointer = load(folder / "CHECKPOINTS.json")
        resolved = {}
        for role in ["last", "best"]:
            relative = Path(pointer[role]["path"])
            path = folder / relative
            if (
                relative.is_absolute()
                or ".." in relative.parts
                or path.is_symlink()
                or digest(path) != pointer[role]["sha256"]
            ):
                raise Rejection("checkpoint transaction identity differs")
            alias = folder / (role + ".pt")
            if (alias.exists() or alias.is_symlink()) and digest(alias) != pointer[
                role
            ]["sha256"]:
                raise Rejection("checkpoint alias differs from transaction")
            resolved[role] = checkpoint(path)
        best, last = resolved["best"], resolved["last"]
        version, width = architecture(config, best["model"])
        if version == 3:
            if baseline is None:
                raise Rejection("residual learning requires original baseline evidence")
            if baseline_values is None:
                baseline_values, baseline_sha, baseline_checked = baseline_arrays(
                    Path(baseline),
                    dataset,
                    manifest,
                    dataset_sha,
                    count,
                    4096,
                    86028157,
                )
            if (
                config.get("baseline_sha256") != baseline_sha
                or config.get("classical_contract") != 1
            ):
                raise Rejection("training consumed a different residual baseline")
        elif baseline is not None:
            raise Rejection("absolute model unexpectedly supplied residual evidence")
        for state in [best, last]:
            if state["schema"] != "caissa-checkpoint-v1" or state["config"] != config:
                raise Rejection("checkpoint configuration differs from seed run")
            architecture(config, state["model"])
            if (
                parameter_hash(state["model"]) != state["current_hash"]
                or state["current_hash"] == state["initial_hash"]
            ):
                raise Rejection("real trained parameter identity differs")
            verify_optimizer(state, config)
        if last["step"] != config["steps"]:
            raise Rejection("seed did not complete its frozen training budget")
        for step, sampler in sampler_states(
            config["seed"],
            [best["step"], last["step"]],
            config["batch"],
            manifest["splits"]["train"],
        ):
            for state in [best, last]:
                if state["step"] == step and state["sampler"] != sampler:
                    raise Rejection(
                        "saved sampler state differs from exact replayed training draws"
                    )
        initial = checkpoint(folder / "initial.pt")
        identity = load(folder / "INITIAL.json")
        if (
            initial["schema"] != "caissa-initial-parameters-v1"
            or initial["config"] != config
            or identity["seed"] != config["seed"]
            or digest(folder / "initial.pt") != identity["sha256"]
        ):
            raise Rejection("original initialization provenance differs")
        architecture(config, initial["model"])
        initial_hash = parameter_hash(initial["model"])
        if (
            initial_hash != initial["initial_hash"]
            or initial_hash != identity["parameter_sha256"]
            or initial_hash != best["initial_hash"]
            or initial_hash != last["initial_hash"]
        ):
            raise Rejection(
                "seed checkpoint does not descend from its saved initialization"
            )
        untrained = validation_loss(
            initial["model"],
            x,
            y,
            count,
            config["outcome_weight"],
            False,
            baseline_values,
        )
        close(
            initial["untrained_validation"],
            untrained,
            "untrained held-out loss differs",
        )
        observations = {}
        for line in (folder / "observations.jsonl").read_text().splitlines():
            row = json.loads(line)
            finite(row)
            step = row["step"]
            if step in observations and any(
                row[key] != observations[step][key]
                for key in [
                    "parameter_sha256",
                    "loss",
                    "validation_quantized",
                    "gradient_norm",
                ]
            ):
                raise Rejection(
                    "resumed observation silently changed a completed checkpoint"
                )
            if (
                row["sampled_positions"] != step * config["batch"]
                or row["gradient_norm"] <= 0
                or not row["parameters_changed"]
            ):
                raise Rejection("learning observations lack real update evidence")
            observations[step] = row
        expected_steps = list(
            range(
                config["checkpoint_every"],
                config["steps"] + 1,
                config["checkpoint_every"],
            )
        )
        if config["steps"] not in expected_steps:
            expected_steps.append(config["steps"])
        if set(observations) != set(expected_steps):
            raise Rejection("missing or unexpected validation checkpoint work")
        losses = []
        for step in expected_steps:
            saved = checkpoint(folder / f"checkpoints/step-{step:08d}.pt")
            if (
                saved["config"] != config
                or saved["step"] != step
                or saved["initial_hash"] != initial_hash
            ):
                raise Rejection("checkpoint chronology differs")
            architecture(config, saved["model"])
            sha = parameter_hash(saved["model"])
            if (
                sha != saved["current_hash"]
                or sha != observations[step]["parameter_sha256"]
            ):
                raise Rejection("validation observation names different parameters")
            actual = validation_loss(
                saved["model"],
                x,
                y,
                count,
                config["outcome_weight"],
                True,
                baseline_values,
            )
            close(
                observations[step]["validation_quantized"],
                actual,
                "independent saved-checkpoint validation loss differs",
            )
            losses.append((actual, step))
        observed_best = min(
            expected_steps,
            key=lambda step: (observations[step]["validation_quantized"], step),
        )
        if best["step"] != observed_best:
            raise Rejection(
                "saved best checkpoint was not selected on validation minimum"
            )
        close(
            best["best_validation"],
            observations[observed_best]["validation_quantized"],
            "best checkpoint running validation minimum differs",
        )
        close(
            last["best_validation"],
            observations[observed_best]["validation_quantized"],
            "last checkpoint running validation minimum differs",
        )
        summary = load(folder / "SUMMARY.json")
        close(
            summary["untrained_validation"],
            untrained,
            "summary initialization loss differs",
        )
        close(
            summary["best_validation"],
            dict((step, value) for value, step in losses)[best["step"]],
            "selected held-out loss differs",
        )
        if (
            summary["test_accessed"] is not False
            or summary["updates"] != config["steps"]
            or summary["final_sha256"] != last["current_hash"]
            or summary["initial_checkpoint_sha256"] != identity["sha256"]
        ):
            raise Rejection("training summary lineage or completed work differs")
        if not summary["best_validation"] < untrained:
            raise Rejection(
                "learned evaluator did not improve held-out loss over initialization"
            )
        seed_observations.append(
            {
                "seed": config["seed"],
                "recorded_origin": origins[config["seed"]],
                "verified_directory": str(folder),
                "initial_parameter_sha256": initial_hash,
                "initial_checkpoint_sha256": identity["sha256"],
                "independent_untrained_validation": untrained,
                "independent_checkpoint_validation": [
                    {"step": step, "loss": value} for value, step in losses
                ],
                "selected_checkpoint_step": best["step"],
                "final_updates": last["updates"],
                "replayed_sampler_values": config["steps"] * config["batch"],
            }
        )
        rows.append(
            {
                "seed": config["seed"],
                # Origin paths are provenance text. Only the explicit supplied
                # directory and immutable checkpoint identities locate inputs.
                "folder": origins[config["seed"]],
                "validation_loss": summary["best_validation"],
                "untrained_validation": summary["untrained_validation"],
                "checkpoint_sha256": pointer["best"]["sha256"],
                "step": best["step"],
                "completed_updates": last["updates"],
            }
        )
    if rule and sorted(seeds) != sorted(rule["training"]["seeds"]):
        raise Rejection("trained seed inventory differs from frozen protocol")
    if len(
        {checkpoint(folder / "initial.pt")["initial_hash"] for folder in runs}
    ) != len(runs):
        raise Rejection(
            "independent training seeds reused identical initial parameters"
        )
    if selected_record["all_seeds"] != rows:
        raise Rejection("selection omitted or changed a trained seed")
    chosen = min(rows, key=lambda row: (row["validation_loss"], row["seed"]))
    if (
        selected_record["selected"] != chosen
        or digest(selection / "selected.pt") != chosen["checkpoint_sha256"]
    ):
        raise Rejection("selected model was not chosen from validation-only ordering")
    verify_export(
        selection / "selected.cai",
        checkpoint(selection / "selected.pt"),
        chosen["checkpoint_sha256"],
    )
    if digest(selection / "selected.cai") != selected_record["network"]["sha256"]:
        raise Rejection("selected numerical export identity differs")
    return {
        "status": "passed",
        "profile": (
            "full-learning-domain" if require_full else "diagnostic-learning-domain"
        ),
        "seeds": sorted(seeds),
        "all_checkpoints_independently_evaluated": sum(
            len(list(folder.glob("checkpoints/step-*.pt"))) for folder in runs
        ),
        "validation_positions_per_checkpoint": count,
        "baseline_scores_independently_checked": baseline_checked,
        "independent_seed_observations": seed_observations,
        "selected_seed": chosen["seed"],
        "dataset_sha256": dataset_sha,
        "network_sha256": digest(selection / "selected.cai"),
        "test_arrays_opened": False,
        "full_acceptance": False,
        "scope": "learning provenance and selection only; original-game replay and playing-strength gates remain separate",
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--runs", type=Path, nargs="+", required=True)
    parser.add_argument("--selection", type=Path, required=True)
    parser.add_argument("--baseline", type=Path)
    parser.add_argument("--protocol", type=Path)
    parser.add_argument("--require-full", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    torch.set_num_threads(2)
    start = time.monotonic()
    try:
        result = verify_learning(
            args.dataset,
            args.runs,
            args.selection,
            args.baseline,
            args.protocol,
            args.require_full,
        )
        result["seconds"] = time.monotonic() - start
        if args.output:
            args.output.write_text(json.dumps(result, indent=2) + "\n")
        print(json.dumps(result))
        return 0
    except (
        ValueError,
        KeyError,
        TypeError,
        IndexError,
        OSError,
        RuntimeError,
    ) as error:
        print(json.dumps({"status": "rejected", "reason": str(error)}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
