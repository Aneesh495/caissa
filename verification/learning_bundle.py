"""Replay original training evidence as one component of the full G07 gate.

The original learning receipt and q1024 export remain original observations.
The deployed q4096 encoding is joined through the selected float identity.
Passing this component does not replace full original-data reconstruction.
"""

import sys
import time
from pathlib import Path

from tools.campaign_process import Campaign, StageFailure, atomic
from verification.bundle import strict_json
from verification.draw_history import typed_equal
from verification.source import require

ORIGINAL_PROTOCOL = "4cf0545699ab141dafe4e3f67fcbdb7b996cbec2b8e0b246fc2137a5dc963f62"
ORIGINAL_MODEL = "92d62149d3a4de184ad93b9f5f04f77e38386992d04d02bd824b33cf3e5241bd"
ORIGINAL_SELECTION = "1cd49b3062986086e74396fce27fbbdf4886a0ce9b5b6b6350533b27e3ac8b84"
LEGACY = {"protocol", "model_campaign", "network", "checkpoint"}
RAW = {"dataset", "baseline", "seeds"}


class LearningEndpointFailure(ValueError):
    def __init__(self, reason, observed):
        super().__init__(reason)
        self.observed = observed


def admit_lineage(bundle, inputs):
    from verification.full_bundle import network_contract

    domain = inputs["domains"]["G07"]
    args = domain["original_learning"]
    require(
        isinstance(args, dict) and LEGACY <= set(args) <= LEGACY | RAW,
        "G07 original-learning descriptor has an invalid field inventory",
    )
    declared = {bundle.reference(ref) for ref in domain["artifacts"]}
    paths = {key: bundle.reference(args[key]) for key in LEGACY}
    require(
        set(paths.values()) <= declared, "G07 original lineage inputs are undeclared"
    )
    for name, expected in [
        ("protocol", ORIGINAL_PROTOCOL),
        ("model_campaign", ORIGINAL_MODEL),
    ]:
        require(
            args[name]["sha256"] == expected,
            "G07 original " + name + " identity differs",
        )
    selection_ref = inputs["learning"]["selection"]
    selection_path = bundle.reference(selection_ref)
    require(
        selection_ref["sha256"] == ORIGINAL_SELECTION and selection_path in declared,
        "G07 original validation-only selection identity differs",
    )
    original = bundle.json(paths["protocol"])
    current = bundle.json(bundle.reference(inputs["protocol"]))
    for section in [
        "data",
        "training",
        "model_campaign",
        "selection",
        "classical_control",
    ]:
        require(
            typed_equal(original[section], current[section]),
            "G07 deployment changed original learning section: " + section,
        )
    model = bundle.json(paths["model_campaign"])
    selection = bundle.json(selection_path)
    chosen = selection["selected"]
    require(
        model["seeds"] == original["training"]["seeds"] == [17, 41, 73]
        and model["updates_per_seed"] == original["training"]["steps"] == 20000
        and model["protocol_sha256"] == ORIGINAL_PROTOCOL
        and model["dataset_sha256"] == inputs["dataset"]["metadata"]["sha256"]
        and model["test_model_metrics_used_for_selection"] is False,
        "G07 original completed learning or no-test contract differs",
    )
    require(
        model["checkpoint_sha256"]
        == args["checkpoint"]["sha256"]
        == inputs["network"]["checkpoint_sha256"]
        == chosen["checkpoint_sha256"]
        and selection["test_accessed"] is False,
        "G07 original selected float checkpoint differs from deployment",
    )
    require(
        args["network"]["sha256"]
        == model["network_sha256"]
        == selection["network"]["sha256"],
        "G07 original learned export was replaced with a derived deployment network",
    )
    network = network_contract(
        bundle,
        {
            "artifact": args["network"],
            "checkpoint_sha256": model["checkpoint_sha256"],
            "classical_contract": 1,
            "neural_weight": 10,
        },
    )
    require(
        network["format"] == 3,
        "G07 original learning export must retain q1024 encoding",
    )
    return (
        args,
        original,
        model,
        {
            "original_model_campaign_sha256": ORIGINAL_MODEL,
            "original_protocol_sha256": ORIGINAL_PROTOCOL,
            "original_selection_sha256": ORIGINAL_SELECTION,
            "original_failed_domains": model["failed_domains"],
            "checkpoint_sha256": model["checkpoint_sha256"],
            "original_network_sha256": model["network_sha256"],
            "deployed_network_sha256": inputs["network"]["artifact"]["sha256"],
            "same_selected_float_checkpoint": True,
            "new_learning_receipt_created": False,
            "full_gate": False,
            "full_acceptance": False,
        },
    )


def inventory(bundle, inputs, args, protocol, model):
    require(
        set(args) == LEGACY | RAW,
        "G07 full raw seed/dataset/baseline inventories required",
    )
    require(
        isinstance(args["dataset"], dict)
        and set(args["dataset"])
        == {"train-features.npy", "validation-features.npy", "validation-targets.npy"},
        "G07 learning requires its train features and validation arrays; test arrays are forbidden",
    )
    require(
        isinstance(args["baseline"], dict)
        and set(args["baseline"])
        == {
            "BASELINES.json",
            "caissa",
            "train-baseline.npy",
            "validation-baseline.npy",
        },
        "G07 original classical baseline inventory differs",
    )
    require(
        isinstance(args["seeds"], dict) and set(args["seeds"]) == {"17", "41", "73"},
        "G07 full raw seed inventory differs",
    )
    steps = list(range(250, 20001, 250))
    for seed in ["17", "41", "73"]:
        raw = args["seeds"][seed]
        require(
            isinstance(raw, dict)
            and set(raw)
            == {"initial", "initial_identity", "observations", "summary", "checkpoints"}
            and isinstance(raw["checkpoints"], dict)
            and set(raw["checkpoints"]) == {str(step) for step in steps},
            "G07 full seed checkpoint chronology or raw inventory differs",
        )
    domain = inputs["domains"]["G07"]
    declared = {bundle.reference(ref) for ref in domain["artifacts"]}
    copies = {}

    def add(name, ref, maximum):
        path = bundle.reference(ref)
        require(path in declared, "G07 raw learning artifact is undeclared")
        require(name not in copies, "G07 staged learning path is duplicated")
        copies[name] = (path, maximum)

    metadata = inputs["dataset"]["metadata"]
    dataset = bundle.json(bundle.reference(metadata))
    add("dataset/DATASET.json", metadata, 4 * 1024**2)
    for name, ref in args["dataset"].items():
        require(
            ref["sha256"] == dataset["files"][name],
            "G07 training or validation array identity differs",
        )
        add("dataset/" + name, ref, 4 * 1024**3)
    baseline = args["baseline"]
    baseline_meta = bundle.json(bundle.reference(baseline["BASELINES.json"]))
    require(
        baseline_meta["config"]["dataset_sha256"] == metadata["sha256"]
        and baseline_meta["config"]["engine_sha256"]
        == baseline["caissa"]["sha256"]
        == model["engine_sha256"]
        and type(baseline_meta["config"]["classical_contract"]) is int
        and baseline_meta["config"]["classical_contract"] == 1
        and baseline_meta["test_accessed"] is False,
        "G07 original classical baseline provenance differs",
    )
    require(
        set(baseline_meta["files"])
        == {"train-baseline.npy", "validation-baseline.npy"},
        "G07 baseline must omit test arrays",
    )
    for name, ref in baseline.items():
        if name.endswith(".npy"):
            require(
                ref["sha256"] == baseline_meta["files"][name],
                "G07 original baseline array identity differs",
            )
        add(
            "baseline/" + name,
            ref,
            4 * 1024**3 if name.endswith(".npy") else 64 * 1024**2,
        )
    add("selection/SELECTION.json", inputs["learning"]["selection"], 4 * 1024**2)
    add("selection/selected.pt", args["checkpoint"], 128 * 1024**2)
    add("selection/selected.cai", args["network"], 4 * 1024**2)
    add("ORIGINAL_PROTOCOL.json", args["protocol"], 4 * 1024**2)
    add("MODEL_CAMPAIGN.json", args["model_campaign"], 4 * 1024**2)
    checkpoint_paths = set()
    for seed in ["17", "41", "73"]:
        common = inputs["learning"]["seeds"][seed]
        config = bundle.json(bundle.reference(common["config"]))
        pointer = bundle.json(bundle.reference(common["checkpoints"]))
        require(
            config["baseline_sha256"] == baseline["BASELINES.json"]["sha256"]
            and config["steps"] == protocol["training"]["steps"]
            and config["checkpoint_every"] == protocol["training"]["checkpoint_every"],
            "G07 raw seed differs from original baseline or checkpoint schedule",
        )
        raw = args["seeds"][seed]
        prefix = "seed" + seed + "/"
        add(prefix + "CONFIG.json", common["config"], 4 * 1024**2)
        add(prefix + "CHECKPOINTS.json", common["checkpoints"], 4 * 1024**2)
        for role, filename, cap in [
            ("initial", "initial.pt", 128 * 1024**2),
            ("initial_identity", "INITIAL.json", 4 * 1024**2),
            ("observations", "observations.jsonl", 32 * 1024**2),
            ("summary", "SUMMARY.json", 4 * 1024**2),
        ]:
            add(prefix + filename, raw[role], cap)
        for step in steps:
            ref = raw["checkpoints"][str(step)]
            path = bundle.reference(ref)
            require(
                path not in checkpoint_paths,
                "G07 raw checkpoints reuse an artifact path",
            )
            checkpoint_paths.add(path)
            relative = f"checkpoints/step-{step:08d}.pt"
            for role in ["best", "last"]:
                if pointer[role]["path"] == relative:
                    require(
                        pointer[role]["sha256"] == ref["sha256"],
                        "G07 actual best/last checkpoint identity differs",
                    )
            add(prefix + relative, ref, 128 * 1024**2)
    return copies


def verify(bundle, inputs, output):
    from tools.heuristic_study import avoid_decisive_matches

    avoid_decisive_matches()
    args, protocol, model, lineage = admit_lineage(bundle, inputs)
    copies = inventory(bundle, inputs, args, protocol, model)
    output = Path(output).resolve()
    require(
        not output.is_relative_to(bundle.root),
        "G07 replay must preserve original evidence",
    )
    output.mkdir(parents=True, exist_ok=False)
    raw = output / "raw"
    raw.mkdir()
    stamps = {}
    for name, (source, cap) in copies.items():
        destination = raw / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        bundle.copy(source, destination, cap)
        stamps[name] = bundle.stamp(destination.stat())
    atomic(output / "ORIGINAL_LINEAGE.json", lineage)
    remaining = min(
        bundle.monotonic_deadline - time.monotonic(), bundle.wall_deadline - time.time()
    )
    require(remaining > 1, "G07 original cumulative replay deadline exhausted")
    code = Path(__file__).resolve().parents[1]
    launcher = "import runpy,sys;sys.path.insert(0,sys.argv.pop(1));runpy.run_module('verification.learning',run_name='__main__')"
    command = [
        sys.executable,
        "-P",
        "-c",
        launcher,
        str(code),
        "--dataset",
        str(raw / "dataset"),
        "--runs",
        *[str(raw / ("seed" + str(seed))) for seed in [17, 41, 73]],
        "--selection",
        str(raw / "selection"),
        "--baseline",
        str(raw / "baseline"),
        "--protocol",
        str(raw / "ORIGINAL_PROTOCOL.json"),
        "--require-full",
    ]
    campaign = Campaign(
        output / "execution",
        {"gate": "G07", "component": "learning", **lineage},
        remaining,
        absolute_deadline=bundle.wall_deadline,
        resource_guard=bundle.tick,
    )
    try:
        failure = None
        try:
            record = campaign.run(
                "independent", command, remaining, maximum_output_bytes=4 * 1024**2
            )
        except StageFailure as error:
            record, failure = error.record, error
        result = strict_json((output / "execution/independent.log").read_bytes())
        for name, stamp in stamps.items():
            require(
                bundle.stamp((raw / name).stat()) == stamp,
                "G07 staged learning input changed during replay",
            )
        observed = result.get("observed", {}) if failure else result
        require(
            observed.get("profile") == "full-learning-domain"
            and observed.get("seeds") == [17, 41, 73]
            and observed.get("all_checkpoints_independently_evaluated") == 240
            and observed.get("validation_positions_per_checkpoint") == 8192
            and observed.get("selected_seed") == 73
            and observed.get("dataset_sha256") == model["dataset_sha256"]
            and observed.get("network_sha256") == model["network_sha256"]
            and observed.get("test_arrays_opened") is False,
            "G07 reader did not reconstruct all three original seed/checkpoint runs",
        )
        if failure:
            if (
                record["exit"] == 1
                and record["reason"] == "nonzero-exit"
                and result.get("reason")
                == "learned evaluator did not improve held-out loss over initialization"
                and observed.get("status") == "failed"
            ):
                campaign.close("failed-learning-endpoint", observed)
                atomic(output / "LEARNING.json", result)
                raise LearningEndpointFailure(result["reason"], observed)
            raise ValueError(
                "G07 independent learning process failed; inspect preserved execution"
            ) from failure
        require(
            result.get("status") == "passed",
            "G07 actual learning endpoint did not pass",
        )
        bundle.tick()
        result.update(
            gate="G07",
            component="learning",
            component_pass=True,
            original_lineage=lineage,
            full_gate=False,
            full_acceptance=False,
            data_reconstruction_required=True,
        )
        campaign.close("passed-learning-component", result)
        atomic(output / "LEARNING.json", result)
        return result
    finally:
        if not campaign.closed:
            campaign.close("failed")
