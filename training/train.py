"""Resumable original training with validation-only model selection."""

import argparse, hashlib, json, math, os, random, time, fcntl
from pathlib import Path
import numpy as np
import torch
from training.corpus import atomic_json, digest
from training.model import CaissaNet, deployed_logits, state_hash


def save(path, value):
    temp = path.with_suffix(".tmp")
    with temp.open("wb") as f:
        torch.save(value, f)
        f.flush()
        os.fsync(f.fileno())
    temp.replace(path)
    directory = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


def targets(rows, weight):
    outcome = rows[:, 0]
    teacher = rows[:, 2] if rows.shape[1] >= 3 else torch.sigmoid(rows[:, 1] / 400)
    return weight * outcome + (1 - weight) * teacher


def finite_state(value):
    if isinstance(value, torch.Tensor):
        if not torch.isfinite(value).all():
            raise ValueError("nonfinite training tensor state")
    elif isinstance(value, np.ndarray):
        if not np.isfinite(value).all():
            raise ValueError("nonfinite training array state")
    elif isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("nonfinite training scalar state")
    elif isinstance(value, dict):
        for nested in value.values():
            finite_state(nested)
    elif isinstance(value, (list, tuple)):
        for nested in value:
            finite_state(nested)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("dataset", type=Path)
    ap.add_argument("output", type=Path)
    ap.add_argument("--network-version", type=int, choices=[2, 3], default=2)
    ap.add_argument("--baseline-directory", type=Path)
    ap.add_argument("--neural-weight", type=int, default=100)
    ap.add_argument("--width", type=int, choices=[32, 64, 128], default=64)
    ap.add_argument("--seed", type=int, required=True)
    ap.add_argument("--steps", type=int, default=1000)
    ap.add_argument("--batch", type=int, default=512)
    ap.add_argument("--lr", type=float, default=0.001)
    ap.add_argument("--outcome-weight", type=float, default=0.5)
    ap.add_argument("--device", choices=["cpu", "mps", "cuda"], default="cpu")
    ap.add_argument("--threads", type=int, default=2)
    ap.add_argument("--checkpoint-every", type=int, default=100)
    ap.add_argument("--resume", action="store_true")
    a = ap.parse_args()
    if not 1 <= a.neural_weight <= 100 or (
        a.neural_weight < 100 and a.network_version != 3
    ):
        ap.error("mixture training requires residual format3 and percentage1..100")
    if (
        not 1 <= a.steps <= 1000000
        or not 16 <= a.batch <= 8192
        or not 0 <= a.outcome_weight <= 1
        or not 1 <= a.threads <= 8
    ):
        ap.error("training budget outside supported bounds")
    if (
        not math.isfinite(a.lr)
        or not 0 < a.lr <= 0.1
        or not 1 <= a.checkpoint_every <= a.steps
    ):
        ap.error("invalid finite learning rate or checkpoint interval")
    if a.device == "mps" and not torch.backends.mps.is_available():
        raise RuntimeError("MPS requested but unavailable")
    if a.device == "cuda" and not torch.cuda.is_available():
        raise RuntimeError("CUDA requested but unavailable")
    torch.set_num_threads(a.threads)
    torch.manual_seed(a.seed)
    random.seed(a.seed)
    np.random.seed(a.seed)
    if a.device == "cpu":
        torch.use_deterministic_algorithms(True)
    manifest = json.loads((a.dataset / "DATASET.json").read_text())
    for filename, sha in manifest["files"].items():
        if filename.startswith("test-"):
            continue
        if digest(a.dataset / filename) != sha:
            raise ValueError("dataset bytes changed")
    dataset_id = digest(a.dataset / "DATASET.json")
    config = {
        k: v
        for k, v in vars(a).items()
        if k
        not in ["resume", "output", "dataset", "network_version", "baseline_directory"]
    }
    if a.neural_weight == 100:
        # Missing means the historical100-percent objective. Keep legacy
        # configurations and exact same-host resume trajectories unchanged.
        del config["neural_weight"]
    else:
        config["mixture_contract"] = "residual-output-ste-round-clamp-truncate-v1"
    config.update(
        {
            "dataset_sha256": dataset_id,
            "schema": "caissa-train-config-v1",
            "torch": str(torch.__version__),
            "network_contract": f"v{a.network_version}-q1024-clip2047-{a.width}-32-16",
            "validation_count": min(8192, manifest["splits"]["validation"]),
            "validation_selection": (
                "first sorted input SHA256 identities; no test arrays opened"
                if manifest.get("schema") == "caissa-dataset-v2"
                else "first sorted canonical SHA256 identities; no test arrays opened"
            ),
        }
    )
    baseline_train = baseline_validation = None
    if a.network_version == 3:
        if a.baseline_directory is None:
            raise ValueError(
                "residual training requires frozen original classical baselines"
            )
        baseline_manifest = json.loads(
            (a.baseline_directory / "BASELINES.json").read_text()
        )
        if (
            baseline_manifest["config"]["dataset_sha256"] != dataset_id
            or baseline_manifest["config"]["classical_contract"] != 1
            or baseline_manifest.get("test_accessed") is not False
        ):
            raise ValueError("residual baseline contract or dataset differs")
        if set(baseline_manifest["files"]) != {
            "train-baseline.npy",
            "validation-baseline.npy",
        }:
            raise ValueError("residual baseline file inventory differs")
        for name, expected in baseline_manifest["files"].items():
            if (
                name not in ["train-baseline.npy", "validation-baseline.npy"]
                or digest(a.baseline_directory / name) != expected
            ):
                raise ValueError("residual baseline byte identity differs")
        baseline_train = np.load(
            a.baseline_directory / "train-baseline.npy",
            mmap_mode="r",
            allow_pickle=False,
        )
        baseline_validation = np.load(
            a.baseline_directory / "validation-baseline.npy",
            mmap_mode="r",
            allow_pickle=False,
        )
        if baseline_train.dtype != np.int16 or baseline_validation.dtype != np.int16:
            raise ValueError("residual baseline dtype differs")
        if baseline_train.shape != (
            manifest["splits"]["train"],
        ) or baseline_validation.shape != (manifest["splits"]["validation"],):
            raise ValueError("residual baseline array shape differs")
        config["baseline_sha256"] = digest(a.baseline_directory / "BASELINES.json")
        config["network_version"] = 3
        config["classical_contract"] = 1
    elif a.baseline_directory is not None:
        raise ValueError("baseline arrays supplied to an absolute evaluator")
    a.output.mkdir(parents=True, exist_ok=True)
    lock_file = (a.output / "TRAIN.lock").open("a")
    fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    cfg = a.output / "CONFIG.json"
    if cfg.exists() and json.loads(cfg.read_text()) != config:
        raise ValueError("resume configuration differs")
    atomic_json(cfg, config)
    train_x = np.load(a.dataset / "train-features.npy", mmap_mode="r")
    train_y = np.load(a.dataset / "train-targets.npy", mmap_mode="r")
    val_x = np.load(a.dataset / "validation-features.npy", mmap_mode="r")
    val_y = np.load(a.dataset / "validation-targets.npy", mmap_mode="r")
    model = CaissaNet(version=a.network_version, width=a.width).to(a.device)
    optimizer = torch.optim.AdamW(model.parameters(), lr=a.lr, weight_decay=0.00001)
    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(
        optimizer, T_max=a.steps, eta_min=a.lr * 0.05
    )
    sampler = np.random.default_rng(a.seed ^ 0x13579)
    initial_hash = state_hash(model)
    first_step = 0
    best = float("inf")
    updates = 0
    checkpoint = a.output / "last.pt"
    pointer = a.output / "CHECKPOINTS.json"
    best_generation = None

    def alias(name, target):
        path = a.output / name
        tmp = a.output / (name + ".link.tmp")
        if tmp.exists() or tmp.is_symlink():
            tmp.unlink()
        os.symlink(target, tmp)
        tmp.replace(path)

    if a.resume and pointer.exists():
        transaction = json.loads(pointer.read_text())
        for role in ["last", "best"]:
            relative = Path(transaction[role]["path"])
            if (
                relative.is_absolute()
                or ".." in relative.parts
                or digest(a.output / relative) != transaction[role]["sha256"]
            ):
                raise ValueError("checkpoint transaction integrity")
            alias(role + ".pt", str(relative))
        checkpoint = a.output / transaction["last"]["path"]
        best_generation = transaction["best"]
    if a.resume:
        state = torch.load(checkpoint, map_location=a.device, weights_only=False)
        finite_state(state)
        if state["config"] != config:
            raise ValueError("checkpoint configuration mismatch")
        model.load_state_dict(state["model"])
        optimizer.load_state_dict(state["optimizer"])
        scheduler.load_state_dict(state["scheduler"])
        sampler.bit_generator.state = state["sampler"]
        torch.set_rng_state(state["torch_rng"].cpu())
        random.setstate(state["python_rng"])
        np.random.set_state(state["numpy_rng"])
        first_step = state["step"]
        best = state["best_validation"]
        initial_hash = state["initial_hash"]
        updates = state["updates"]
        if a.device == "cuda":
            torch.cuda.set_rng_state_all(state["device_rng"])
        if a.device == "mps":
            torch.mps.set_rng_state(state["device_rng"].cpu())
    elif checkpoint.exists() or pointer.exists():
        raise ValueError("existing checkpoint requires explicit --resume")
    validation_indices = np.arange(min(8192, len(val_x)), dtype=np.int64)

    def validation(quantized):
        model.eval()
        total = 0.0
        count = 0
        with torch.inference_mode():
            for offset in range(0, len(validation_indices), a.batch):
                idx = validation_indices[offset : offset + a.batch]
                x = torch.from_numpy(np.array(val_x[idx], dtype=np.int64)).to(a.device)
                y = torch.from_numpy(np.array(val_y[idx])).to(a.device)
                baseline = (
                    torch.from_numpy(
                        np.array(baseline_validation[idx], dtype=np.float32)
                    ).to(a.device)
                    if baseline_validation is not None
                    else None
                )
                prediction = model(
                    x,
                    quantized=quantized,
                    baseline=baseline,
                )
                prediction = deployed_logits(
                    prediction, baseline, a.neural_weight, quantized
                )
                loss = torch.nn.functional.binary_cross_entropy_with_logits(
                    prediction,
                    targets(y, a.outcome_weight),
                    reduction="sum",
                )
                total += float(loss)
                count += len(idx)
        model.train()
        return total / count

    start = time.monotonic()
    untrained = validation(False) if first_step == 0 else state["untrained_validation"]
    initial_path = a.output / "initial.pt"
    if first_step == 0 and initial_path.exists():
        # A process can die after initialization but before its first optimizer
        # transaction. Recreate the seeded start and preserve its original bytes.
        from verification.learning import checkpoint as read_checkpoint, parameter_hash

        origin = read_checkpoint(initial_path)
        identity = json.loads((a.output / "INITIAL.json").read_text())
        if (
            origin["schema"] != "caissa-initial-parameters-v1"
            or origin["config"] != config
            or origin["initial_hash"] != initial_hash
            or parameter_hash(origin["model"]) != initial_hash
            or origin["untrained_validation"] != untrained
            or identity["sha256"] != digest(initial_path)
            or identity["parameter_sha256"] != initial_hash
            or identity["seed"] != a.seed
        ):
            raise ValueError("saved initialization differs from exact seeded recovery")
    elif first_step == 0:
        save(
            initial_path,
            {
                "schema": "caissa-initial-parameters-v1",
                "config": config,
                "model": model.state_dict(),
                "initial_hash": initial_hash,
                "untrained_validation": untrained,
            },
        )
        atomic_json(
            a.output / "INITIAL.json",
            {
                "schema": "caissa-initial-identity-v1",
                "sha256": digest(initial_path),
                "parameter_sha256": initial_hash,
                "seed": a.seed,
            },
        )
    log = (a.output / "observations.jsonl").open("a" if a.resume else "w")
    try:
        for step in range(first_step, a.steps):
            indices = sampler.integers(0, len(train_x), size=a.batch)
            x = torch.from_numpy(np.array(train_x[indices], dtype=np.int64)).to(
                a.device
            )
            y = torch.from_numpy(np.array(train_y[indices])).to(a.device)
            optimizer.zero_grad(set_to_none=True)
            quantized = step >= a.steps // 2
            baseline = (
                torch.from_numpy(
                    np.array(baseline_train[indices], dtype=np.float32)
                ).to(a.device)
                if baseline_train is not None
                else None
            )
            prediction = model(
                x,
                quantized=quantized,
                baseline=baseline,
            )
            prediction = deployed_logits(
                prediction, baseline, a.neural_weight, quantized
            )
            loss = torch.nn.functional.binary_cross_entropy_with_logits(
                prediction, targets(y, a.outcome_weight)
            )
            if not torch.isfinite(loss):
                raise ValueError("nonfinite training loss")
            loss.backward()
            norm = torch.nn.utils.clip_grad_norm_(
                model.parameters(), 5.0, error_if_nonfinite=True
            )
            if float(norm) > 0:
                updates += 1
            optimizer.step()
            scheduler.step()
            with torch.no_grad():
                model.embedding.weight[-1].zero_()
            if (step + 1) % a.checkpoint_every == 0 or step + 1 == a.steps:
                value = validation(True)
                current_hash = state_hash(model)
                record = {
                    "step": step + 1,
                    "loss": float(loss.detach()),
                    "validation_quantized": value,
                    "gradient_norm": float(norm),
                    "parameters_changed": current_hash != initial_hash,
                    "parameter_sha256": current_hash,
                    "seconds": time.monotonic() - start,
                    "sampled_positions": (step + 1) * a.batch,
                    "qa_training": quantized,
                }
                log.write(json.dumps(record) + "\n")
                log.flush()
                print(json.dumps(record), flush=True)
                is_best = value < best
                best = min(best, value)
                state = {
                    "schema": "caissa-checkpoint-v1",
                    "config": config,
                    "model": model.state_dict(),
                    "optimizer": optimizer.state_dict(),
                    "scheduler": scheduler.state_dict(),
                    "sampler": sampler.bit_generator.state,
                    "torch_rng": torch.get_rng_state(),
                    "python_rng": random.getstate(),
                    "numpy_rng": np.random.get_state(),
                    "device_rng": (
                        torch.cuda.get_rng_state_all()
                        if a.device == "cuda"
                        else torch.mps.get_rng_state() if a.device == "mps" else None
                    ),
                    "step": step + 1,
                    "best_validation": best,
                    "initial_hash": initial_hash,
                    "current_hash": current_hash,
                    "updates": updates,
                    "untrained_validation": untrained,
                }
                finite_state(state)
                generations = a.output / "checkpoints"
                generations.mkdir(exist_ok=True)
                relative = f"checkpoints/step-{step+1:08d}.pt"
                save(a.output / relative, state)
                current_generation = {
                    "path": relative,
                    "sha256": digest(a.output / relative),
                }
                if is_best:
                    best_generation = current_generation
                if best_generation is None:
                    # A legacy resume retains its existing complete best checkpoint.
                    legacy = "checkpoints/legacy-best.pt"
                    if not (a.output / legacy).exists():
                        save(
                            a.output / legacy,
                            torch.load(
                                a.output / "best.pt",
                                map_location="cpu",
                                weights_only=False,
                            ),
                        )
                    best_generation = {
                        "path": legacy,
                        "sha256": digest(a.output / legacy),
                    }
                atomic_json(
                    pointer,
                    {
                        "schema": "caissa-checkpoint-transaction-v1",
                        "last": current_generation,
                        "best": best_generation,
                    },
                )
                alias("last.pt", relative)
                alias("best.pt", best_generation["path"])
        summary = {
            "status": (
                "diagnostic-learning"
                if manifest["splits"]["train"] < 10000000
                or manifest["counts"]["completed_games"] < 100000
                or not manifest.get("functional_deduplication", False)
                else "full-data-training-completed"
            ),
            "seed": a.seed,
            "steps": a.steps,
            "updates": updates,
            "initial_sha256": initial_hash,
            "final_sha256": state_hash(model),
            "untrained_validation": untrained,
            "best_validation": best,
            "improved": best < untrained,
            "dataset_sha256": dataset_id,
            "test_accessed": False,
            "initial_checkpoint_sha256": (
                digest(initial_path) if initial_path.exists() else None
            ),
            "seconds_this_session": time.monotonic() - start,
            "training_positions": len(train_x),
            "validation_positions_evaluated": len(validation_indices),
        }
        atomic_json(a.output / "SUMMARY.json", summary)
        print(json.dumps(summary))
    finally:
        log.close()


if __name__ == "__main__":
    main()
