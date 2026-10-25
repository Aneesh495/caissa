"""Independent full-bundle identity and experimental-lineage admission.

Admission verifies relationships, not saved pass booleans. Domain execution is
still required. Unsupported or missing semantic replay keeps acceptance false.
"""

import argparse
import hashlib
import json
import struct
import subprocess
import time
import zlib
from pathlib import Path

from verification.bundle import Bundle, digest_text, strict_json
from verification.source import PRODUCT, require, verify_checkout

GATES = {f"G{i:02d}" for i in range(1, 17)}
RUNTIME_GATES = GATES - {"G07", "G14", "G16"}
NEURAL_GATES = {"G02", "G06", "G08", "G09", "G10", "G12", "G13", "G15"}


def integer(value, minimum, reason):
    require(type(value) is int and value >= minimum, reason)
    return value


def finite(value, reason):
    import math

    require(type(value) in {int, float} and math.isfinite(value), reason)
    return value


def metadata(bundle, reference):
    value = bundle.json(bundle.reference(reference))
    require(isinstance(value, dict), "full domain metadata must be an object")
    return value


def network_contract(bundle, descriptor):
    require(
        isinstance(descriptor, dict), "full deployment descriptor must be an object"
    )
    raw = bundle.bytes(bundle.reference(descriptor["artifact"]), 4 * 1024 * 1024)
    require(len(raw) >= 120, "full selected network header is truncated")
    version, feature, features, width, dense1, dense2, scale, clip = struct.unpack_from(
        "<8I", raw, 8
    )
    require(
        raw[:8] == b"CAISSAN" + str(version).encode("ascii")
        and version in {3, 4}
        and feature == 1
        and features == 12288
        and width == 64
        and dense1 == 32
        and dense2 == 16,
        "full selected network architecture or baseline family differs",
    )
    require(
        (scale, clip) == ({3: (1024, 2047), 4: (4096, 8188)}[version]),
        "full selected network integer lattice differs",
    )
    payload, flags, checksum, baseline = struct.unpack_from("<4I", raw, 104)
    expected_payload = (
        features * width * 2
        + width * 4
        + dense1 * width * 4
        + dense1 * 4
        + dense2 * dense1 * 2
        + dense2 * 4
        + dense2 * 2
        + 4
    )
    require(
        payload == expected_payload
        and len(raw) == payload + 120
        and flags == 0
        and checksum == zlib.crc32(raw[120:])
        and baseline == 1,
        "full selected network payload, CRC or classical contract differs",
    )
    identity = raw[40:104].decode("ascii")
    require(
        identity == digest_text(descriptor["checkpoint_sha256"]),
        "full network is not the selected float checkpoint",
    )
    require(
        type(descriptor["classical_contract"]) is int
        and descriptor["classical_contract"] == 1
        and type(descriptor["neural_weight"]) is int
        and descriptor["neural_weight"] == 10,
        "full deployment changed original classical evaluation or selected mixture",
    )
    return {
        "format": version,
        "scale": scale,
        "clip": clip,
        "classical_contract": baseline,
        "neural_weight": 10,
        "checkpoint_sha256": identity,
    }


def data_lineage(bundle, inputs, protocol):
    reference = inputs["dataset"]["metadata"]
    dataset = metadata(bundle, reference)
    require(
        reference["sha256"] == protocol["data"]["dataset_sha256"],
        "full data differs from the frozen experiment",
    )
    require(
        dataset["schema"] == "caissa-dataset-v2"
        and dataset["functional_deduplication"] is True,
        "full data lacks functional-input split screening",
    )
    train = integer(
        dataset["splits"]["train"],
        10000000,
        "full distinct training-input floor failed",
    )
    games = integer(
        dataset["counts"]["completed_games"],
        100000,
        "full completed original-game floor failed",
    )
    require(
        train == dataset["counts"]["distinct_train_inputs"],
        "full data training counts disagree",
    )
    require(
        dataset["corpus_config"]["engine_sha256"] == protocol["data"]["teacher_sha256"],
        "full data teacher identity differs from the original acquisition",
    )
    require(
        dataset["target_columns"]
        == [
            "mean_outcome_stm",
            "mean_original_teacher_cp",
            "mean_original_teacher_win_probability",
        ],
        "full data target perspective or teacher aggregation differs",
    )
    for name in ["config/studies.json", "config/strength-openings.json"]:
        path = bundle.reference(inputs["heldout"][name])
        require(
            dataset["heldout_inputs"][name] == bundle.identities[path],
            "full held-out study/opening bytes differ from data screening",
        )
    return {
        "training_inputs": train,
        "completed_original_games": games,
        "dataset_sha256": reference["sha256"],
        "semantic_reconstruction_required": True,
    }


def learning_lineage(bundle, inputs, protocol, deployment):
    learning = inputs["learning"]
    selection = metadata(bundle, learning["selection"])
    require(
        selection["dataset_sha256"] == protocol["data"]["dataset_sha256"]
        and selection["test_accessed"] is False,
        "full learning changed data or accessed test selection",
    )
    expected_seeds = protocol["training"]["seeds"]
    require(
        len(expected_seeds) >= 3
        and len(set(expected_seeds)) == len(expected_seeds)
        and all(type(seed) is int for seed in expected_seeds),
        "full learning needs three distinct original seeds",
    )
    require(
        set(learning["seeds"]) == {str(seed) for seed in expected_seeds},
        "full learning omitted or replaced a frozen seed",
    )
    rows = selection["all_seeds"]
    require(
        len(rows) == len(expected_seeds)
        and {row["seed"] for row in rows} == set(expected_seeds),
        "full selection did not retain every seed",
    )
    candidates = []
    for seed in expected_seeds:
        entry = learning["seeds"][str(seed)]
        config, checkpoints = metadata(bundle, entry["config"]), metadata(
            bundle, entry["checkpoints"]
        )
        require(
            config["seed"] == seed
            and config["dataset_sha256"] == selection["dataset_sha256"]
            and config["neural_weight"] == deployment["neural_weight"]
            and config["classical_contract"] == 1,
            "full seed configuration changed data, mixture or classical baseline",
        )
        steps = integer(config["steps"], 1, "full seed update budget is invalid")
        require(
            steps == protocol["training"]["steps"],
            "full seed update budget differs from frozen training",
        )
        observed = [row for row in rows if row["seed"] == seed][0]
        require(
            observed["completed_updates"] == steps and 0 < observed["step"] <= steps,
            "full seed did not complete its entire update budget",
        )
        loss = finite(
            observed["validation_loss"], "full selected seed loss is nonfinite"
        )
        require(
            loss
            < finite(
                observed["untrained_validation"], "full untrained loss is nonfinite"
            ),
            "full seed validation loss did not improve over its own initialization",
        )
        require(
            checkpoints["schema"] == "caissa-checkpoint-transaction-v1"
            and checkpoints["best"]["sha256"] == observed["checkpoint_sha256"]
            and checkpoints["best"]["path"]
            == f"checkpoints/step-{observed['step']:08d}.pt"
            and checkpoints["last"]["path"] == f"checkpoints/step-{steps:08d}.pt",
            "full selected or final optimizer checkpoint identity differs",
        )
        candidates.append((loss, seed, observed["step"], observed["checkpoint_sha256"]))
    best = min(candidates)
    chosen = selection["selected"]
    require(
        (
            chosen["validation_loss"],
            chosen["seed"],
            chosen["step"],
            chosen["checkpoint_sha256"],
        )
        == best,
        "full model was not selected by the declared validation-only criterion",
    )
    require(
        best[3]
        == deployment["checkpoint_sha256"]
        == inputs["network"]["checkpoint_sha256"],
        "full deployed network changed the validation-selected checkpoint",
    )
    return {
        "seeds": expected_seeds,
        "selected_seed": best[1],
        "selected_step": best[2],
        "checkpoint_sha256": best[3],
        "optimizer_and_validation_replay_required": True,
    }


def inspect(bundle, checkout, expected_commit, expected_inputs_sha256):
    raw_inputs = bundle.bytes("FULL_INPUTS.json")
    require(
        hashlib.sha256(raw_inputs).hexdigest() == digest_text(expected_inputs_sha256),
        "full input declaration differs from external frozen identity",
    )
    inputs = strict_json(raw_inputs)
    require(isinstance(inputs, dict), "full input declaration must be an object")
    require(
        inputs["schema"] == "caissa-full-inputs-v1"
        and inputs["source_commit"] == expected_commit,
        "full input source or schema differs",
    )
    verify_checkout(
        checkout, bundle.json("SOURCE_INPUTS.json"), expected_commit, PRODUCT
    )
    bundle.verify_manifest()
    protocol = metadata(bundle, inputs["protocol"])
    require(
        protocol["status"] == "frozen"
        and protocol["schema"]
        in {"caissa-experiment-protocol-v3", "caissa-experiment-protocol-v4"},
        "full experiment protocol is unsupported or not frozen",
    )
    matches = protocol["matches"]
    integer(matches["neural_pairs"], 2000, "full neural sample floor failed")
    require(
        isinstance(matches["external_pairs"], list)
        and len(matches["external_pairs"]) >= 3,
        "full external sample lacks three settings",
    )
    require(
        sum(
            integer(n, 1, "full external setting has no work")
            for n in matches["external_pairs"]
        )
        >= 1000,
        "full external sample floor failed",
    )
    require(
        finite(matches["minimum_neural_gain_elo"], "nonfinite neural gain endpoint")
        >= 50
        and finite(
            matches["minimum_neural_lower_elo_exclusive"],
            "nonfinite neural lower endpoint",
        )
        >= 0
        and matches["confidence"] == 0.95,
        "full neural-gain threshold or uncertainty was weakened",
    )
    engine = bundle.reference(inputs["engine"])
    deployment = network_contract(bundle, inputs["network"])
    training_network = protocol["network"]
    require(
        deployment["neural_weight"] == training_network["neural_weight"]
        and deployment["clip"] * training_network["scale"]
        == training_network["clip"] * deployment["scale"],
        "full deployment changed the real activation cap or selected mixture",
    )
    data = data_lineage(bundle, inputs, protocol)
    learning = learning_lineage(bundle, inputs, protocol, deployment)
    require(
        set(inputs["domains"]) == GATES,
        "full gate inventory is incomplete or duplicated",
    )
    pending = {}
    for gate in sorted(GATES):
        domain = inputs["domains"][gate]
        require(
            domain["source_commit"] == expected_commit,
            "full gate source identity differs: " + gate,
        )
        if gate in RUNTIME_GATES:
            require(
                domain["engine_sha256"] == bundle.identities[engine],
                "full gate used a different engine: " + gate,
            )
        if gate in NEURAL_GATES:
            require(
                domain["network_sha256"] == inputs["network"]["artifact"]["sha256"],
                "full gate used a different evaluator: " + gate,
            )
        references = domain.get("artifacts", [])
        require(
            isinstance(references, list),
            "full gate artifact inventory is malformed: " + gate,
        )
        for reference in references:
            bundle.reference(reference)
        # A receipt's status is never a semantic implementation or replay.
        pending[gate] = (
            "raw domain artifacts missing"
            if not references
            else "independent full-domain semantic adapter required"
        )
    return {
        "status": "incomplete",
        "profile": "full",
        "full_acceptance": False,
        "source_commit": expected_commit,
        "inputs_sha256": expected_inputs_sha256,
        "verified_relationships": {
            "deployment": deployment,
            "data": data,
            "learning": learning,
        },
        "pending_semantic_gates": pending,
        "scope": "Artifact integrity, committed product source and experiment-lineage admission only; no full gate certified",
    }


def verify(
    root,
    checkout,
    expected_commit,
    expected_inputs_sha256,
    maximum_seconds=600,
    replay_output=None,
):
    require(
        expected_inputs_sha256 is not None,
        "full verification requires external expected-inputs SHA256",
    )
    from tools.heuristic_study import avoid_decisive_matches

    avoid_decisive_matches(Path(checkout) / "runs")
    if replay_output is not None:
        avoid_decisive_matches(Path(__file__).resolve().parents[1] / "runs")
    with Bundle(root, maximum_seconds) as bundle:
        review = inspect(bundle, checkout, expected_commit, expected_inputs_sha256)
        inputs = bundle.json("FULL_INPUTS.json")
        domain = inputs["domains"]["G01"]
        if domain.get("driver") == "rules-v1":
            if replay_output is None:
                review["pending_semantic_gates"][
                    "G01"
                ] = "rules replay requires an external --replay-output directory"
            else:
                output = Path(replay_output).resolve()
                require(
                    not output.is_relative_to(bundle.root),
                    "full replay must preserve the original evidence",
                )
                arguments = domain["rules"]
                paths = {
                    key: bundle.reference(arguments[key])
                    for key in ["profile", "fixtures", "summary", "observations"]
                }
                declared = {bundle.reference(ref) for ref in domain["artifacts"]}
                require(
                    set(paths.values()) <= declared,
                    "G01 replay inputs are absent from its declared raw artifacts",
                )
                from verification.rules import verify as verify_rules

                remaining = min(
                    bundle.monotonic_deadline - time.monotonic(),
                    bundle.wall_deadline - time.time(),
                )
                result = verify_rules(
                    bundle.root / paths["observations"],
                    bundle.root / paths["summary"],
                    bundle.root / inputs["engine"]["path"],
                    inputs["engine"]["sha256"],
                    bundle.root / paths["profile"],
                    arguments["profile"]["sha256"],
                    bundle.root / paths["fixtures"],
                    arguments["observations"]["sha256"],
                    output / "G01",
                    maximum_seconds=min(900, remaining),
                )
                require(
                    result["full_gate"] is True,
                    "G01 replay did not complete its full required sample",
                )
                review["verified_semantic_gates"] = {"G01": result}
                del review["pending_semantic_gates"]["G01"]
        domain = inputs["domains"]["G02"]
        if domain.get("driver") == "restoration-v1":
            if replay_output is None:
                review["pending_semantic_gates"][
                    "G02"
                ] = "restoration replay requires an external --replay-output directory"
            else:
                from verification.restoration import verify as verify_restoration

                output = Path(replay_output).resolve()
                require(
                    not output.is_relative_to(bundle.root),
                    "full replay must preserve the original evidence",
                )
                arguments = domain["restoration"]
                paths = {
                    key: bundle.reference(arguments[key])
                    for key in ["profile", "config", "summary", "observations"]
                }
                declared = {bundle.reference(ref) for ref in domain["artifacts"]}
                require(
                    len(set(paths.values())) == 4 and set(paths.values()) <= declared,
                    "G02 replay requires distinct declared raw artifacts",
                )
                config = bundle.json(paths["config"])
                require(
                    config.get("source_commit") == expected_commit,
                    "G02 producer source differs from full deployment",
                )
                remaining = min(
                    bundle.monotonic_deadline - time.monotonic(),
                    bundle.wall_deadline - time.time(),
                )
                result = verify_restoration(
                    bundle.root / paths["observations"],
                    bundle.root / paths["summary"],
                    bundle.root / paths["config"],
                    bundle.root / inputs["engine"]["path"],
                    inputs["engine"]["sha256"],
                    bundle.root / inputs["network"]["artifact"]["path"],
                    inputs["network"]["artifact"]["sha256"],
                    bundle.root / paths["profile"],
                    arguments["profile"]["sha256"],
                    arguments["observations"]["sha256"],
                    output / "G02",
                    maximum_seconds=min(3600, remaining),
                )
                require(
                    result["full_gate"] is True,
                    "G02 replay did not complete its full required sample",
                )
                bundle.tick()
                review.setdefault("verified_semantic_gates", {})["G02"] = result
                del review["pending_semantic_gates"]["G02"]
        domain = inputs["domains"]["G03"]
        if domain.get("driver") == "draw-history-v1":
            if replay_output is None:
                review["pending_semantic_gates"][
                    "G03"
                ] = "draw-history replay requires an external --replay-output directory"
            else:
                from verification.draw_history import verify as verify_draw_history

                output = Path(replay_output).resolve()
                require(
                    not output.is_relative_to(bundle.root),
                    "full replay must preserve the original evidence",
                )
                arguments = domain["draw_history"]
                paths = {
                    key: bundle.reference(arguments[key])
                    for key in ["profile", "config", "summary", "observations"]
                }
                declared = {bundle.reference(ref) for ref in domain["artifacts"]}
                require(
                    len(set(paths.values())) == 4 and set(paths.values()) <= declared,
                    "G03 replay requires distinct declared raw artifacts",
                )
                config = bundle.json(paths["config"])
                require(
                    config.get("source_commit") == expected_commit,
                    "G03 producer source differs from full deployment",
                )
                remaining = min(
                    bundle.monotonic_deadline - time.monotonic(),
                    bundle.wall_deadline - time.time(),
                )
                result = verify_draw_history(
                    bundle.root / paths["observations"],
                    bundle.root / paths["summary"],
                    bundle.root / paths["config"],
                    bundle.root / inputs["engine"]["path"],
                    inputs["engine"]["sha256"],
                    bundle.root / inputs["network"]["artifact"]["path"],
                    inputs["network"]["artifact"]["sha256"],
                    bundle.root / paths["profile"],
                    arguments["profile"]["sha256"],
                    arguments["observations"]["sha256"],
                    output / "G03",
                    maximum_seconds=min(240, remaining),
                )
                require(
                    result["full_gate"] is True,
                    "G03 replay did not complete all frozen histories",
                )
                bundle.tick()
                review.setdefault("verified_semantic_gates", {})["G03"] = result
                del review["pending_semantic_gates"]["G03"]
        domain = inputs["domains"]["G05"]
        if domain.get("driver") == "search-semantics-v1":
            if replay_output is None:
                review["pending_semantic_gates"][
                    "G05"
                ] = "search replay requires an external --replay-output directory"
            else:
                from verification.search_semantics import verify as verify_search

                output = Path(replay_output).resolve()
                require(
                    not output.is_relative_to(bundle.root),
                    "full replay must preserve the original evidence",
                )
                arguments = domain["search_semantics"]
                paths = {
                    key: bundle.reference(arguments[key])
                    for key in ["profile", "config", "summary", "observations"]
                }
                declared = {bundle.reference(ref) for ref in domain["artifacts"]}
                require(
                    len(set(paths.values())) == 4 and set(paths.values()) <= declared,
                    "G05 replay requires distinct declared raw artifacts",
                )
                require(
                    bundle.json(paths["config"]).get("source_commit")
                    == expected_commit,
                    "G05 producer source differs from full deployment",
                )
                remaining = min(
                    bundle.monotonic_deadline - time.monotonic(),
                    bundle.wall_deadline - time.time(),
                )
                result = verify_search(
                    bundle.root / paths["observations"],
                    bundle.root / paths["summary"],
                    bundle.root / paths["config"],
                    bundle.root / inputs["engine"]["path"],
                    inputs["engine"]["sha256"],
                    bundle.root / paths["profile"],
                    arguments["profile"]["sha256"],
                    arguments["observations"]["sha256"],
                    output / "G05",
                    maximum_seconds=min(600, remaining),
                )
                require(
                    result["full_gate"] is True,
                    "G05 replay did not complete the frozen semantic sample",
                )
                bundle.tick()
                review.setdefault("verified_semantic_gates", {})["G05"] = result
                del review["pending_semantic_gates"]["G05"]
        domain = inputs["domains"]["G04"]
        if domain.get("driver") == "protocol-v2":
            if replay_output is None:
                review["pending_semantic_gates"][
                    "G04"
                ] = "protocol replay requires an external --replay-output directory"
            else:
                from verification.protocol import verify as verify_protocol

                output = Path(replay_output).resolve()
                require(
                    not output.is_relative_to(bundle.root),
                    "full replay must preserve the original evidence",
                )
                arguments = domain["uci_transcript"]
                paths = {
                    key: bundle.reference(arguments[key])
                    for key in ["config", "summary", "transcript", "stderr"]
                }
                require(
                    len(set(paths.values())) == 4,
                    "G04 replay requires distinct raw artifacts",
                )
                declared = {bundle.reference(ref) for ref in domain["artifacts"]}
                require(
                    set(paths.values()) <= declared,
                    "G04 replay inputs are absent from its declared raw artifacts",
                )
                config = bundle.json(paths["config"])
                require(
                    type(config.get("requested")) is int
                    and config["requested"] >= 10000,
                    "full protocol workload below 10000 sequences",
                )
                require(
                    config.get("engine_sha256") == inputs["engine"]["sha256"],
                    "G04 transcript executable differs from full deployment",
                )
                destination = output / "G04"
                destination.mkdir(parents=True, exist_ok=False)
                for key, filename, maximum in [
                    ("config", "CONFIG.json", 4 * 1024 * 1024),
                    ("summary", "summary.json", 4 * 1024 * 1024),
                    ("transcript", "transcript.jsonl", 512 * 1024 * 1024),
                    ("stderr", "stderr.log", 1024 * 1024),
                ]:
                    (destination / filename).write_bytes(
                        bundle.bytes(paths[key], maximum)
                    )
                result = verify_protocol(
                    destination, inputs["engine"]["sha256"], full=True, tick=bundle.tick
                )
                bundle.tick()
                review.setdefault("verified_semantic_gates", {})["G04"] = result
                del review["pending_semantic_gates"]["G04"]
        domain = inputs["domains"]["G06"]
        if domain.get("driver") == "numerical-probes-v1":
            if replay_output is None:
                review["pending_semantic_gates"][
                    "G06"
                ] = "numerical replay requires an external --replay-output directory"
            else:
                from verification.numerical_bundle import (
                    NumericalEndpointFailure,
                    verify as verify_numerical,
                )

                try:
                    result = verify_numerical(
                        bundle, inputs, Path(replay_output).resolve() / "G06"
                    )
                except NumericalEndpointFailure as error:
                    review.setdefault("failed_semantic_gates", {})["G06"] = {
                        "status": "failed",
                        "reason": str(error),
                        "observed": error.observed,
                        "full_acceptance": False,
                    }
                else:
                    review.setdefault("verified_semantic_gates", {})["G06"] = result
                del review["pending_semantic_gates"]["G06"]
        domain = inputs["domains"]["G07"]
        if domain.get("driver") == "original-learning-v1":
            if replay_output is None:
                review["pending_semantic_gates"][
                    "G07"
                ] = "original learning replay requires an external --replay-output directory"
            else:
                from verification.learning_bundle import (
                    LearningEndpointFailure,
                    verify as verify_learning,
                )

                try:
                    result = verify_learning(
                        bundle, inputs, Path(replay_output).resolve() / "G07-learning"
                    )
                except LearningEndpointFailure as error:
                    review.setdefault("failed_semantic_components", {}).setdefault(
                        "G07", {}
                    )["learning"] = {
                        "status": "failed",
                        "reason": str(error),
                        "observed": error.observed,
                        "full_gate": False,
                        "full_acceptance": False,
                    }
                else:
                    review.setdefault("verified_semantic_components", {}).setdefault(
                        "G07", {}
                    )["learning"] = result
                review["pending_semantic_gates"][
                    "G07"
                ] = "full original-data reconstruction and joint G07 component audit required"
        for gate in ["G08", "G09"]:
            domain = inputs["domains"][gate]
            if domain.get("driver") != "strength-journals-v1":
                continue
            if replay_output is None:
                review["pending_semantic_gates"][
                    gate
                ] = "strength replay requires an external --replay-output directory"
                continue
            from verification.strength_bundle import verify as verify_strength
            from verification.strength import StrengthFailure

            try:
                result = verify_strength(
                    bundle, inputs, gate, Path(replay_output).resolve() / gate
                )
            except StrengthFailure as error:
                review.setdefault("failed_semantic_gates", {})[gate] = {
                    "status": "failed",
                    "reason": str(error),
                    "observed": error.observed,
                    "full_acceptance": False,
                }
                del review["pending_semantic_gates"][gate]
                continue
            require(
                result["full_gate"] is True, "strength full-domain replay incomplete"
            )
            review.setdefault("verified_semantic_gates", {})[gate] = result
            del review["pending_semantic_gates"][gate]
        return review


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("evidence", type=Path)
    parser.add_argument("--checkout", type=Path, required=True)
    parser.add_argument("--expected-commit", required=True)
    parser.add_argument("--expected-inputs-sha256", required=True)
    parser.add_argument("--maximum-seconds", type=float, default=600)
    parser.add_argument("--replay-output", type=Path)
    args = parser.parse_args()
    try:
        result = verify(
            args.evidence,
            args.checkout,
            args.expected_commit,
            args.expected_inputs_sha256,
            args.maximum_seconds,
            args.replay_output,
        )
        print(json.dumps(result))
        return 0 if result.get("full_acceptance") is True else 2
    except (
        ValueError,
        TypeError,
        IndexError,
        OSError,
        KeyError,
        struct.error,
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
