"""Read current full-input metadata without running or certifying a campaign."""

import hashlib
from pathlib import Path

from verification.bundle import strict_json, digest_text
from verification.source import relative_path, require


def bounded_bytes(path):
    require(
        path.is_file()
        and not path.is_symlink()
        and path.stat().st_size <= 4 * 1024 * 1024,
        "readiness metadata is missing, linked or excessive",
    )
    return path.read_bytes()


def document(path):
    raw = bounded_bytes(path)
    value = strict_json(raw)
    require(isinstance(value, dict), "readiness metadata must be an object")
    return value, hashlib.sha256(raw).hexdigest()


def inspect(root, protocol_name="config/protocol-v3.json", dataset=None):
    root = Path(root).resolve()
    protocol_path = root / relative_path(protocol_name)
    require(
        protocol_path.resolve().is_relative_to(root),
        "readiness protocol escaped the checkout",
    )
    protocol, protocol_sha = document(protocol_path)
    require(
        protocol["status"] == "frozen",
        "readiness requires a prospectively frozen protocol",
    )
    expected = digest_text(protocol["data"]["dataset_sha256"])
    if dataset is None:
        candidates = sorted((root / "data").glob("*/DATASET.json"))
        require(len(candidates) <= 128, "readiness dataset discovery ceiling exceeded")
    else:
        selected = Path(dataset)
        candidates = [selected / "DATASET.json" if selected.is_dir() else selected]
    matching = []
    for path in candidates:
        require(
            path.resolve().is_relative_to(root) and not path.parent.is_symlink(),
            "readiness dataset escaped the trusted checkout",
        )
        raw = bounded_bytes(path)
        identity = hashlib.sha256(raw).hexdigest()
        if identity == expected:
            value = strict_json(raw)
            require(
                isinstance(value, dict), "frozen dataset metadata must be an object"
            )
            matching.append((path, value))
        elif dataset is not None:
            raise ValueError(
                "explicit readiness dataset differs from the frozen identity"
            )
    require(
        len(matching) <= 1,
        "multiple frozen dataset copies exist; select --dataset explicitly",
    )
    counts = {
        "dataset_path": None,
        "dataset_sha256": expected,
        "observed_training_positions": None,
        "observed_completed_games": None,
    }
    if matching:
        path, value = matching[0]
        train, games = value["splits"]["train"], value["counts"]["completed_games"]
        require(
            type(train) is int and type(games) is int and train >= 0 and games >= 0,
            "readiness data counts must be nonnegative integers",
        )
        require(
            train == value["counts"]["distinct_train_inputs"],
            "readiness training counts disagree",
        )
        counts.update(
            {
                "dataset_path": str(path.relative_to(root)),
                "observed_training_positions": train,
                "observed_completed_games": games,
            }
        )
    model = None
    output = protocol.get("model_campaign", {}).get("output")
    if output is not None:
        path = root / relative_path(output) / "MODEL_CAMPAIGN.json"
        if path.is_file():
            require(
                path.resolve().is_relative_to(root),
                "readiness model receipt escaped the checkout",
            )
            receipt, identity = document(path)
            require(
                receipt["dataset_sha256"] == expected,
                "recorded model used a different full dataset",
            )
            model = {
                "path": str(path.relative_to(root)),
                "sha256": identity,
                "recorded_status": receipt["status"],
                "recorded_failed_domains": receipt["failed_domains"],
                "seeds": receipt["seeds"],
                "updates_per_seed": receipt["updates_per_seed"],
            }
    return {
        "profile": "full",
        "status": "blocked",
        "full_acceptance": False,
        "protocol": protocol_name,
        "protocol_sha256": protocol_sha,
        **counts,
        "required_training_positions": 10000000,
        "required_completed_games": 100000,
        "recorded_model_campaign": model,
        "metadata_floor_observed": bool(matching)
        and counts["observed_training_positions"] >= 10000000
        and counts["observed_completed_games"] >= 100000,
        "reason": "Metadata readiness only. Full-domain semantic replay, the complete coordinator and remaining required gates are incomplete. Existing failures are preserved.",
    }
