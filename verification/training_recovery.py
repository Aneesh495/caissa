"""Independently reconstruct interrupted training state and the repaired journal.

No gradients, model selection or training implementation imports occur here.
The component never certifies the original-data recovery or complete G11 gate.
"""

import argparse
import hashlib
import json
import math
from pathlib import Path

import numpy as np
from verification.bundle import Bundle, strict_json
from verification.source import require

torch = None

DATASET = "51ab630fd7c986efa3010d0f2fc8b6bc1108af0917dc4ec408253a9de21be20e"
STEPS = [20, 40, 60, 80, 100]
MODEL_FIELDS = [
    "model",
    "optimizer",
    "scheduler",
    "sampler",
    "torch_rng",
    "numpy_rng",
    "python_rng",
    "device_rng",
    "config",
    "step",
    "updates",
    "initial_hash",
    "current_hash",
    "best_validation",
    "untrained_validation",
    "schema",
]


def same(left, right):
    if isinstance(left, torch.Tensor):
        return (
            isinstance(right, torch.Tensor)
            and left.dtype == right.dtype
            and left.shape == right.shape
            and torch.equal(left, right)
        )
    if isinstance(left, np.ndarray):
        return (
            isinstance(right, np.ndarray)
            and left.dtype == right.dtype
            and left.shape == right.shape
            and np.array_equal(left, right)
        )
    if isinstance(left, dict):
        return (
            isinstance(right, dict)
            and list(left) == list(right)
            and all(same(left[key], right[key]) for key in left)
        )
    if isinstance(left, (list, tuple)):
        return (
            type(left) is type(right)
            and len(left) == len(right)
            and all(same(a, b) for a, b in zip(left, right))
        )
    return type(left) is type(right) and left == right


def admit(config, engine, source):
    require(
        config.get("schema") == "caissa-training-recovery-v1"
        and config.get("profile") == "training-recovery-component-only"
        and config.get("source_commit") == source
        and config.get("engine_sha256") == engine
        and config.get("dataset_sha256") == DATASET,
        "G11 training recovery source, program or original diagnostic data differs",
    )
    require(
        all(
            type(config.get(key)) is int and config[key] == value
            for key, value in {
                "seed": 17,
                "steps": 100,
                "checkpoint_every": 20,
                "neural_weight": 10,
                "classical_contract": 1,
                "maximum_seconds": 180,
                "maximum_output_bytes": 1024**3,
                "minimum_free_bytes": 10 * 1024**3,
            }.items()
        )
        and config.get("test_arrays_accessed") is False
        and config.get("full_G11_certified") is False,
        "G11 training component scope, original resources or objective differs",
    )
    start, end = config.get("started_unix"), config.get("deadline_unix")
    require(
        all(type(v) in [int, float] and math.isfinite(v) for v in [start, end])
        and end - start == 180,
        "G11 training original wall boundary differs",
    )


def verify(root, engine, source, maximum_seconds=60):
    from tools.host_lease import HostLease, inherited
    from tools.heuristic_study import avoid_decisive_matches

    runs = Path(__file__).resolve().parents[1] / "runs"
    avoid_decisive_matches(runs)
    lease = None if inherited(runs / "TIMED_STRENGTH.lock") else HostLease(runs)
    try:
        global torch
        import torch as tensor_runtime

        torch = tensor_runtime
        return reconstruct(root, engine, source, maximum_seconds)
    finally:
        if lease is not None:
            lease.close()


def reconstruct(root, engine, source, maximum_seconds):
    from verification.learning import (
        architecture,
        baseline_arrays,
        checkpoint,
        close,
        parameter_hash,
        sampler_states,
        validation_loss,
        verify_optimizer,
    )

    torch.set_num_threads(2)
    with Bundle(root, maximum_seconds) as bundle:
        bundle.verify_manifest()
        config = bundle.json("CONFIG.json")
        admit(config, engine, source)
        kill = bundle.json("KILL.json")
        require(
            type(kill.get("signal")) is int
            and kill["signal"] == 9
            and type(kill.get("actual_exit")) is int
            and kill["actual_exit"] == -9
            and type(kill.get("pid")) is int
            and kill["pid"] > 0,
            "G11 training requires the actual forced SIGKILL exit",
        )
        a, b = kill.get("signal_monotonic_ns"), kill.get("reaped_monotonic_ns")
        require(
            type(a) is int and type(b) is int and a > 0 and 0 <= b - a <= 5_000_000_000,
            "G11 killed trainer was not reaped within its boundary",
        )
        marker = bundle.json("before/RECOVERY_READY.json")
        require(
            bundle.identities["before/RECOVERY_READY.json"] == kill["boundary_sha256"]
            and marker.get("schema") == "caissa-training-recovery-boundary-v1"
            and type(marker.get("uncommitted_step")) is int
            and marker["uncommitted_step"] == 40
            and marker["committed"]["path"] == "checkpoints/step-00000020.pt",
            "G11 uncommitted training boundary differs",
        )
        pointer = bundle.json("before/CHECKPOINTS.json")
        require(
            pointer["last"] == marker["committed"]
            and marker["committed"]["sha256"]
            == bundle.identities["before/checkpoints/step-00000020.pt"]
            == bundle.identities["recovered/checkpoints/step-00000020.pt"],
            "G11 protected committed generation changed",
        )
        for name in [
            "CONFIG.json",
            "INITIAL.json",
            "initial.pt",
            "RECOVERY_READY.json",
        ]:
            require(
                bundle.bytes("before/" + name, 16 * 1024**2)
                == bundle.bytes("recovered/" + name, 16 * 1024**2),
                "G11 protected initialization or boundary bytes changed",
            )
        raw_before = bundle.bytes("before/observations.jsonl")
        records = [strict_json(line) for line in raw_before.splitlines()]
        require(
            [r["step"] for r in records] == [20, 40],
            "G11 killed writer lacks the intended uncommitted observation",
        )
        torn = bundle.bytes("before/injected-torn-tail.bin")
        require(torn == b'{"step":', "G11 original torn journal fixture differs")
        prefix, tail = (
            raw_before[: raw_before.index(b"\n") + 1],
            raw_before[raw_before.index(b"\n") + 1 :] + torn,
        )
        recovered_record = bundle.json("recovered/RECOVERED_JOURNAL.json")
        tail_name = "recovery-tails/" + hashlib.sha256(tail).hexdigest() + ".bin"
        require(
            recovered_record
            == {
                "schema": "caissa-observation-recovery-v1",
                "committed_step": 20,
                "original_sha256": hashlib.sha256(raw_before + torn).hexdigest(),
                "preserved_prefix_sha256": hashlib.sha256(prefix).hexdigest(),
                "discarded_tail_sha256": hashlib.sha256(tail).hexdigest(),
                "preserved_prefix_bytes": len(prefix),
                "discarded_tail_bytes": len(tail),
                "tail": tail_name,
            }
            and bundle.bytes("recovered/" + tail_name) == tail,
            "G11 repaired journal failed to preserve its exact removed bytes",
        )
        require(
            bundle.bytes("recovered/observations.jsonl").startswith(prefix),
            "G11 committed journal prefix was rewritten",
        )
        expected = {
            "CONFIG.json",
            "KILL.json",
            "dataset/DATASET.json",
            *{
                f"dataset/{s}-{k}.npy"
                for s in ["train", "validation"]
                for k in ["features", "targets"]
            },
            *{
                "baseline/" + n
                for n in [
                    "CONFIG.json",
                    "BASELINES.json",
                    "PROGRESS.json",
                    "caissa",
                    "train-baseline.npy",
                    "validation-baseline.npy",
                ]
            },
            *{
                f"{role}/{n}"
                for role in ["whole", "recovered"]
                for n in [
                    "CONFIG.json",
                    "INITIAL.json",
                    "initial.pt",
                    "CHECKPOINTS.json",
                    "observations.jsonl",
                    "SUMMARY.json",
                ]
            },
            *{
                f"{role}/checkpoints/step-{step:08d}.pt"
                for role in ["whole", "recovered"]
                for step in STEPS
            },
            *{
                "before/" + n
                for n in [
                    "CONFIG.json",
                    "INITIAL.json",
                    "initial.pt",
                    "CHECKPOINTS.json",
                    "observations.jsonl",
                    "RECOVERY_READY.json",
                    "checkpoints/step-00000020.pt",
                    "injected-torn-tail.bin",
                ]
            },
            "recovered/RECOVERY_READY.json",
            "recovered/RECOVERED_JOURNAL.json",
            "recovered/" + tail_name,
        }
        require(
            set(bundle.identities) == expected,
            "G11 training raw inventory is missing or extra",
        )
        require(
            bundle.identities["dataset/DATASET.json"] == DATASET
            and bundle.identities["baseline/caissa"] == engine,
            "G11 recovery substituted its original data or classical evaluator",
        )
        manifest = bundle.json("dataset/DATASET.json")
        for split in ["train", "validation"]:
            for kind in ["features", "targets"]:
                name = f"{split}-{kind}.npy"
                require(
                    bundle.identities["dataset/" + name] == manifest["files"][name],
                    "G11 original data bytes differ",
                )
        count = manifest["splits"]["validation"]
        baseline, baseline_sha, checks = baseline_arrays(
            Path(root) / "baseline",
            Path(root) / "dataset",
            manifest,
            DATASET,
            count,
            128,
            17,
        )
        x = np.load(
            Path(root) / "dataset/validation-features.npy",
            mmap_mode="r",
            allow_pickle=False,
        )
        y = np.load(
            Path(root) / "dataset/validation-targets.npy",
            mmap_mode="r",
            allow_pickle=False,
        )
        sampler = dict(sampler_states(17, STEPS, 256, manifest["splits"]["train"]))
        values = {}
        for role in ["whole", "recovered"]:
            cfg = bundle.json(role + "/CONFIG.json")
            require(
                cfg.get("schema") == "caissa-train-config-v1"
                and cfg.get("dataset_sha256") == DATASET
                and cfg.get("baseline_sha256") == baseline_sha
                and all(
                    type(cfg.get(k)) is int and cfg[k] == v
                    for k, v in {
                        "seed": 17,
                        "steps": 100,
                        "batch": 256,
                        "checkpoint_every": 20,
                        "threads": 2,
                        "neural_weight": 10,
                        "classical_contract": 1,
                        "width": 64,
                    }.items()
                )
                and cfg.get("network_version") == 3
                and cfg.get("device") == "cpu"
                and cfg.get("lr") == 0.001
                and cfg.get("outcome_weight") == 0.5
                and cfg.get("validation_count") == count,
                "G11 trainer used a different recovery configuration",
            )
            initial = checkpoint(Path(root) / role / "initial.pt")
            identity = bundle.json(role + "/INITIAL.json")
            require(
                architecture(cfg, initial["model"]) == (3, 64)
                and same(initial["config"], cfg)
                and identity["sha256"] == bundle.identities[role + "/initial.pt"]
                and identity["parameter_sha256"]
                == parameter_hash(initial["model"])
                == initial["initial_hash"],
                "G11 original random initialization identity differs",
            )
            initial_loss = validation_loss(
                initial["model"], x, y, count, 0.5, False, baseline, 10
            )
            close(
                initial["untrained_validation"],
                initial_loss,
                "G11 initialization loss differs",
            )
            observations = [
                strict_json(line)
                for line in bundle.bytes(role + "/observations.jsonl").splitlines()
            ]
            require(
                [r["step"] for r in observations] == STEPS,
                "G11 recovery journal contains duplicate, missing or torn observations",
            )
            states = {}
            for step, observation in zip(STEPS, observations):
                bundle.tick()
                state = checkpoint(
                    Path(root) / role / f"checkpoints/step-{step:08d}.pt"
                )
                require(
                    set(state) == set(MODEL_FIELDS)
                    and type(state["step"]) is int
                    and state["step"] == step
                    and same(state["config"], cfg)
                    and state["initial_hash"] == initial["initial_hash"]
                    and state["current_hash"] == parameter_hash(state["model"]),
                    "G11 checkpoint source, generation or parameter identity differs",
                )
                architecture(cfg, state["model"])
                verify_optimizer(state, cfg)
                require(
                    same(state["sampler"], sampler[step]),
                    "G11 sampler does not match exact original draws",
                )
                require(
                    observation["parameter_sha256"] == state["current_hash"]
                    and observation["sampled_positions"] == step * 256
                    and observation["gradient_norm"] > 0
                    and observation["parameters_changed"] is True
                    and observation["qa_training"] is (step > 50),
                    "G11 checkpoint observation lacks actual update provenance",
                )
                loss = validation_loss(
                    state["model"], x, y, count, 0.5, True, baseline, 10
                )
                close(
                    observation["validation_quantized"],
                    loss,
                    "G11 recovered validation graph differs",
                )
                states[step] = state
            transaction = bundle.json(role + "/CHECKPOINTS.json")
            for ref in [transaction["last"], transaction["best"]]:
                require(
                    ref["path"] in {f"checkpoints/step-{s:08d}.pt" for s in STEPS}
                    and ref["sha256"] == bundle.identities[role + "/" + ref["path"]],
                    "G11 recovered checkpoint pointer differs",
                )
            require(
                transaction["last"]["path"] == "checkpoints/step-00000100.pt",
                "G11 recovery ended before the fixed endpoint",
            )
            best_step = min(
                observations, key=lambda row: (row["validation_quantized"], row["step"])
            )["step"]
            require(
                transaction["best"]["path"] == f"checkpoints/step-{best_step:08d}.pt",
                "G11 recovery changed validation-only best checkpoint",
            )
            summary = bundle.json(role + "/SUMMARY.json")
            require(
                summary.get("test_accessed") is False
                and summary.get("updates") == 100
                and summary.get("final_sha256") == states[100]["current_hash"]
                and summary.get("initial_checkpoint_sha256") == identity["sha256"],
                "G11 recovery summary differs from actual canonical states",
            )
            close(
                summary["best_validation"],
                observations[STEPS.index(best_step)]["validation_quantized"],
                "G11 recovery selected validation loss differs",
            )
            values[role] = (initial, states, observations)
        left, right = values["whole"], values["recovered"]
        require(
            same(left[0], right[0]),
            "G11 resumed initialization differs from uninterrupted",
        )
        for step in STEPS:
            for field in MODEL_FIELDS:
                require(
                    same(left[1][step][field], right[1][step][field]),
                    "G11 recovered tensor/state differs: " + field,
                )
        for one, two in zip(left[2], right[2]):
            require(
                same(
                    {k: v for k, v in one.items() if k != "seconds"},
                    {k: v for k, v in two.items() if k != "seconds"},
                ),
                "G11 recovered observation differs from uninterrupted trajectory",
            )
        for old, whole in zip(records, left[2]):
            require(
                same(
                    {k: v for k, v in old.items() if k != "seconds"},
                    {k: v for k, v in whole.items() if k != "seconds"},
                ),
                "G11 interrupted observation differs from the actual trajectory",
            )
        return {
            "status": "passed",
            "component_pass": True,
            "actual_forced_exit": -9,
            "checkpoint_pairs": 5,
            "exact_state_fields": MODEL_FIELDS,
            "independent_classical_checks": checks,
            "removed_tail_preserved": True,
            "test_arrays_opened": False,
            "full_G11_certified": False,
            "original_data_recovery_and_final_binding_still_required": True,
        }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("evidence", type=Path)
    parser.add_argument("--engine-sha256", required=True)
    parser.add_argument("--source-commit", required=True)
    args = parser.parse_args()
    try:
        result = verify(args.evidence, args.engine_sha256, args.source_commit)
    except (
        ValueError,
        TypeError,
        KeyError,
        OSError,
        RuntimeError,
        AssertionError,
    ) as error:
        print(
            json.dumps(
                {"status": "rejected", "reason": str(error), "component_pass": False}
            )
        )
        return 1
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
