"""Stream immutable prepared data into coverage and target-distribution counts.

No model, gradients, checkpoint selection or test-model metrics are involved.
Raw-observation histograms and deduplicated input rows stay separate.
"""

import argparse
import hashlib
import json
import math
import time
from pathlib import Path

import numpy as np

from tools.campaign_process import atomic
from verification.protocol import read_json

FEATURE_COUNT = 12288
SPLITS = ("train", "validation", "test")
BINS = {
    "material": np.arange(1.5, 33.5).tolist(),
    "phase": np.arange(-0.5, 25.5).tolist(),
    "outcome": np.linspace(0, 1, 21).tolist(),
    "teacher_cp": np.linspace(-2000, 2000, 41).tolist(),
    "teacher_probability": np.linspace(0, 1, 21).tolist(),
    "absolute_target_disagreement": np.linspace(0, 1, 21).tolist(),
}


def require(condition, reason):
    if not condition:
        raise ValueError(reason)


def empty_counts():
    return {
        name: np.zeros(len(edges) - 1, dtype=np.int64) for name, edges in BINS.items()
    }


def observations(features, targets):
    require(
        features.ndim == 3 and features.shape[1:] == (2, 32),
        "feature profile shape differs",
    )
    require(
        features.dtype == np.dtype("uint16") and targets.dtype == np.dtype("float32"),
        "profile numerical storage differs",
    )
    require(targets.shape == (len(features), 3), "target profile shape differs")
    require(
        np.isfinite(targets).all()
        and (targets[:, [0, 2]] >= 0).all()
        and (targets[:, [0, 2]] <= 1).all(),
        "nonfinite or invalid probability target",
    )
    require(
        (np.abs(targets[:, 1]) <= 32000).all(),
        "teacher score exceeds original search bounds",
    )
    require(
        (features <= FEATURE_COUNT).all(),
        "feature index exceeds the declared transformer",
    )
    valid = features < FEATURE_COUNT
    kinds = (features // 64) % 12
    material = valid[:, 0].sum(axis=1)
    require(
        np.array_equal(material, valid[:, 1].sum(axis=1)),
        "perspectives disagree on material count",
    )
    for perspective in (0, 1):
        for king in (5, 11):
            require(
                (
                    ((kinds[:, perspective] == king) & valid[:, perspective]).sum(
                        axis=1
                    )
                    == 1
                ).all(),
                "profile features require one king of each color",
            )
    weights = np.array([0, 1, 1, 2, 4, 0], dtype=np.uint8)
    phase = np.minimum(
        24, np.where(valid[:, 0], weights[kinds[:, 0] % 6], 0).sum(axis=1)
    )
    other_phase = np.minimum(
        24, np.where(valid[:, 1], weights[kinds[:, 1] % 6], 0).sum(axis=1)
    )
    require(
        np.array_equal(phase, other_phase), "perspectives disagree on tapered phase"
    )
    y = targets.astype(np.float64)
    difference = y[:, 0] - y[:, 2]
    values = {
        "material": material,
        "phase": phase,
        "outcome": y[:, 0],
        "teacher_cp": np.clip(y[:, 1], -2000, 2000),
        "teacher_probability": y[:, 2],
        "absolute_target_disagreement": np.abs(difference),
    }
    histograms = {
        name: np.histogram(value, bins=BINS[name])[0] for name, value in values.items()
    }
    require(
        all(int(count.sum()) == len(features) for count in histograms.values()),
        "profile histogram lost input rows",
    )
    return histograms, {
        "rows": len(features),
        "sum_outcome": float(y[:, 0].sum()),
        "sum_teacher_probability": float(y[:, 2].sum()),
        "sum_absolute_target_disagreement": float(np.abs(difference).sum()),
        "sum_squared_target_disagreement": float((difference * difference).sum()),
        "teacher_score_tail_rows": int((np.abs(y[:, 1]) > 2000).sum()),
        "fractional_outcome_rows": int(((y[:, 0] > 0) & (y[:, 0] < 1)).sum()),
    }


def digest(path, deadline):
    result = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024**2), b""):
            require(
                time.monotonic() < deadline,
                "data profile cumulative active ceiling exhausted",
            )
            result.update(block)
    return result.hexdigest()


def profile(dataset, output, maximum_seconds=300, chunk=32768):
    require(
        math.isfinite(maximum_seconds)
        and 0 < maximum_seconds <= 1800
        and 1 <= chunk <= 262144,
        "finite profile resources required",
    )
    output.mkdir(parents=True, exist_ok=False)
    started, wall = time.monotonic(), time.time()
    deadline = started + maximum_seconds
    manifest_path = dataset / "DATASET.json"
    manifest_sha = digest(manifest_path, deadline)
    manifest = read_json(manifest_path.read_text())
    require(
        manifest["schema"] == "caissa-dataset-v2"
        and manifest["functional_deduplication"] is True,
        "profile requires the functional-input dataset",
    )
    raw = manifest["histograms"]
    for name in (
        "material",
        "phase",
        "ply",
        "outcome",
        "clock",
        "teacher",
        "search_depth",
    ):
        require(
            type(raw[name]) is dict and raw[name], "raw histogram is absent: " + name
        )
        require(
            all(
                math.isfinite(float(label)) and type(n) is int and n >= 0
                for label, n in raw[name].items()
            ),
            "invalid raw histogram bin",
        )
        require(
            sum(raw[name].values()) == manifest["counts"]["raw_positions"],
            "raw histogram total differs: " + name,
        )
    atomic(
        output / "CONFIG.json",
        {
            "dataset_sha256": manifest_sha,
            "maximum_seconds": maximum_seconds,
            "chunk_rows": chunk,
            "bins": BINS,
            "model_evaluated": False,
            "test_model_metrics_used": False,
            "full_acceptance": False,
        },
    )
    inputs, reports = {}, {}
    for split in SPLITS:
        paths = [
            dataset / f"{split}-{suffix}.npy" for suffix in ("features", "targets")
        ]
        for path in paths:
            identity = digest(path, deadline)
            require(
                identity == manifest["files"][path.name],
                "profile input differs from dataset identity: " + path.name,
            )
            inputs[path.name] = identity
        x, y = (np.load(path, mmap_mode="r", allow_pickle=False) for path in paths)
        require(
            len(x) == len(y) == manifest["splits"][split] and 0 < len(x) <= 30000000,
            "profile split size differs",
        )
        counts, sums = empty_counts(), {}
        for begin in range(0, len(x), chunk):
            require(
                time.monotonic() < deadline and time.time() - wall < maximum_seconds,
                "data profile cumulative deadline exhausted",
            )
            histograms, moment = observations(
                x[begin : begin + chunk], y[begin : begin + chunk]
            )
            for name, values in histograms.items():
                counts[name] += values
            for name, value in moment.items():
                sums[name] = sums.get(name, 0) + value
            atomic(
                output / "PROGRESS.json",
                {
                    "split": split,
                    "completed_rows": min(begin + chunk, len(x)),
                    "total_rows": len(x),
                    "seconds": time.monotonic() - started,
                },
            )
        n = sums["rows"]
        reports[split] = {
            "rows": n,
            "histograms": {name: values.tolist() for name, values in counts.items()},
            "sums": sums,
            "means": {
                name.removeprefix("sum_"): value / n
                for name, value in sums.items()
                if name.startswith("sum_")
            },
        }
        del x, y
    for name, expected in inputs.items():
        require(
            digest(dataset / name, deadline) == expected,
            "profile input changed during scan: " + name,
        )
    require(
        digest(manifest_path, deadline) == manifest_sha,
        "dataset metadata changed during profile",
    )
    require(
        time.monotonic() < deadline and time.time() - wall < maximum_seconds,
        "data profile cumulative deadline exhausted",
    )
    result = {
        "schema": "caissa-data-profile-v1",
        "status": "completed data coverage observations",
        "dataset_sha256": manifest_sha,
        "array_sha256": inputs,
        "feature_contract": "12288 indices; two perspectives; uint16 padding12288",
        "bins": BINS,
        "raw_observation_histograms": raw,
        "source_counts": manifest["counts"],
        "splits": reports,
        "weighting": "Each exported functional input receives equal weight within its split; raw-observation histograms retain duplicate observations separately.",
        "scope": "Dataset label/coverage statistics only. Teacher/outcome disagreement on averaged labels is not held-out model performance or engine Elo. No architecture, seed, checkpoint or training-budget selection uses these test-label distributions.",
        "seconds": time.monotonic() - started,
        "model_evaluated": False,
        "test_model_metrics_used": False,
        "full_acceptance": False,
    }
    atomic(output / "PROFILE.json", result)
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--maximum-seconds", type=float, default=300)
    args = parser.parse_args()
    result = profile(args.dataset, args.output, args.maximum_seconds)
    print(
        json.dumps(
            {
                "status": result["status"],
                "rows": {s: result["splits"][s]["rows"] for s in SPLITS},
                "seconds": result["seconds"],
                "full_acceptance": False,
            }
        )
    )


if __name__ == "__main__":
    main()
