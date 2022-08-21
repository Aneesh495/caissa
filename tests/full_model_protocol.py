"""Reject incomplete identities and weakened full model/strength contracts."""

import argparse
import copy
import hashlib
import json
from pathlib import Path
from tools.full_learning import frozen_rule


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    draft = json.loads(Path("config/protocol-v3.proposed.json").read_text())
    path = args.output / "PROTOCOL.json"
    path.write_text(json.dumps(draft) + "\n")
    observed = []

    def rejected(label, rule, reason):
        path.write_text(json.dumps(rule) + "\n")
        expected = hashlib.sha256(path.read_bytes()).hexdigest()
        try:
            frozen_rule(path, expected)
        except ValueError as error:
            assert reason in str(error), (label, str(error))
            observed.append({"case": label, "reason": str(error)})
        else:
            raise AssertionError("invalid full protocol admitted: " + label)

    rejected("inactive-proposal", draft, "not frozen")
    active = copy.deepcopy(draft)
    active["status"] = "frozen"
    rejected("missing-data-identity", active, "identity is absent")
    active["data"]["dataset_sha256"] = "1" * 64
    active["data"]["finalization_sha256"] = "2" * 64
    path.write_text(json.dumps(active) + "\n")
    assert frozen_rule(path, hashlib.sha256(path.read_bytes()).hexdigest()) == active
    cases = [
        ("seed-replacement", "training", "seeds", [17, 41, 99], "seed inventory"),
        ("updates-reduced", "training", "steps", 19999, "update budget"),
        ("batch-reduced", "training", "batch", 1024, "update budget"),
        ("mixture-changed", "training", "neural_weight", 25, "numerical settings"),
        ("architecture-changed", "network", "width", 128, "architecture"),
        ("probes-reduced", "network", "probes", 99999, "numerical sample"),
        ("error-weakened", "network", "maximum_float_error_cp", 33, "numerical sample"),
        (
            "budget-expanded",
            "model_campaign",
            "maximum_wall_seconds",
            21601,
            "cumulative resources",
        ),
        (
            "early-stop",
            "model_campaign",
            "early_stopping",
            True,
            "cumulative resources",
        ),
        (
            "transitions-reduced",
            "model_campaign",
            "native_transitions",
            999999,
            "restoration sample",
        ),
        (
            "data-floor-reduced",
            "data",
            "minimum_training_inputs",
            9999999,
            "data endpoints",
        ),
        ("neural-sample-reduced", "matches", "neural_pairs", 1999, "strength sample"),
        (
            "external-sample-reduced",
            "matches",
            "external_pairs",
            [333, 333, 333],
            "strength sample",
        ),
        (
            "gain-weakened",
            "matches",
            "minimum_neural_gain_elo",
            49,
            "neural-gain endpoint",
        ),
        (
            "lower-weakened",
            "matches",
            "minimum_neural_lower_elo_exclusive",
            -1,
            "neural-gain endpoint",
        ),
    ]
    for label, section, key, value, reason in cases:
        changed = copy.deepcopy(active)
        changed[section][key] = value
        rejected(label, changed, reason)
    report = {
        "status": "passed",
        "controls": observed,
        "scope": "Frozen contract checks only; no full learning or strength observation",
        "full_acceptance": False,
    }
    (args.output / "CONTROLS.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report))


if __name__ == "__main__":
    main()
