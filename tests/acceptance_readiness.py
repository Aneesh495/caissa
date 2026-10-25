"""A full readiness report selects frozen bytes and preserves failed domains."""

import argparse
import hashlib
import json
import tempfile
from pathlib import Path

from tools.full_readiness import inspect


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    with tempfile.TemporaryDirectory(prefix="caissa-readiness-") as temporary:
        root = Path(temporary)
        for path in ["data/a-legacy", "data/z-frozen", "config", "runs/model"]:
            (root / path).mkdir(parents=True)
        legacy = {
            "splits": {"train": 99999999},
            "counts": {"completed_games": 999999, "distinct_train_inputs": 99999999},
        }
        actual = {
            "splits": {"train": 10578434},
            "counts": {"completed_games": 229582, "distinct_train_inputs": 10578434},
        }
        (root / "data/a-legacy/DATASET.json").write_text(json.dumps(legacy))
        path = root / "data/z-frozen/DATASET.json"
        path.write_text(json.dumps(actual))
        identity = hashlib.sha256(path.read_bytes()).hexdigest()
        protocol = {
            "status": "frozen",
            "data": {"dataset_sha256": identity},
            "model_campaign": {"output": "runs/model"},
        }
        (root / "config/protocol-v3.json").write_text(json.dumps(protocol))
        model = {
            "dataset_sha256": identity,
            "status": "completed with failed gates",
            "failed_domains": ["G06"],
            "seeds": [17, 41, 73],
            "updates_per_seed": 20000,
        }
        (root / "runs/model/MODEL_CAMPAIGN.json").write_text(json.dumps(model))
        report = inspect(root)
        assert (
            report["observed_training_positions"] == 10578434
            and report["metadata_floor_observed"] is True
        )
        assert report["recorded_model_campaign"]["recorded_failed_domains"] == ["G06"]
        assert report["full_acceptance"] is False and report["status"] == "blocked"
        try:
            inspect(root, dataset=root / "data/a-legacy")
        except ValueError as error:
            assert "frozen identity" in str(error)
        else:
            raise AssertionError("wrong explicit data accepted")
        (root / "data/a-legacy/DATASET.json").write_bytes(
            b"unrelated old interrupted metadata"
        )
        assert inspect(root)["observed_training_positions"] == 10578434
        path.unlink()
        missing = inspect(root)
        assert (
            missing["observed_training_positions"] is None
            and missing["metadata_floor_observed"] is False
        )
    output = {
        "status": "passed",
        "frozen_identity_selected": True,
        "failed_domain_preserved": True,
        "missing_data_remains_unknown": True,
        "scope": "Synthetic metadata-only readiness fixture",
        "full_acceptance": False,
    }
    (args.output / "CONTROLS.json").write_text(json.dumps(output, indent=2) + "\n")
    print(json.dumps(output))


if __name__ == "__main__":
    main()
