"""Bounded full original learning with validation-only selection and raw failures.

A completed numerical or restoration domain cannot conceal failed learning.
All seeds finish their declared updates before any seed is selected.
"""

import argparse
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

from tools.campaign_process import Campaign, StageFailure, atomic
from tools.finalize_corpus import archive_source
from tools.power_guard import BATTERY_POLICY, PowerGuard
from tools.recovery_scope import RecoveryScope
from verification.acquisition import sha
from verification.protocol import read_json
from verification.verify import source_files


def frozen_rule(path, expected):
    if sha(path) != expected:
        raise ValueError(
            "full model protocol differs from its external frozen identity"
        )
    rule = read_json(Path(path).read_text())
    if rule["schema"] != "caissa-experiment-protocol-v3" or rule["status"] != "frozen":
        raise ValueError("full model protocol is not frozen")
    for name in [
        "dataset_sha256",
        "finalization_sha256",
        "finalization_protocol_sha256",
        "pair_manifest_sha256",
    ]:
        value = rule["data"][name]
        if (
            type(value) is not str
            or len(value) != 64
            or any(c not in "0123456789abcdef" for c in value)
        ):
            raise ValueError("full model data/finalization identity is absent: " + name)
    train, network, resources = (
        rule["training"],
        rule["network"],
        rule["model_campaign"],
    )
    if (
        train["seeds"] != [17, 41, 73]
        or resources["training_order"] != train["seeds"]
        or train["steps"] != 20000
        or train["batch"] != 2048
        or train["checkpoint_every"] != 250
    ):
        raise ValueError("full seed inventory or declared update budget differs")
    if (
        train["threads"] != 2
        or train["device"] != "cpu"
        or train["lr"] != 0.001
        or train["outcome_weight"] != 0.5
        or train["neural_weight"] != 10
    ):
        raise ValueError("full training numerical settings differ")
    if (
        network["format"],
        network["width"],
        network["scale"],
        network["clip"],
        network["neural_weight"],
    ) != (3, 64, 1024, 2047, 10) or network["dense"] != [32, 16]:
        raise ValueError("full residual architecture or deployed mixture differs")
    if (
        network["probes"] != 100000
        or network["probe_seed"] != 86028157
        or network["maximum_float_error_cp"] != 32
        or network["error_contract"] != "unclamped-quantization-and-clamped-inference"
    ):
        raise ValueError("full numerical sample or error endpoint differs")
    if (
        resources["maximum_wall_seconds"] != 86400
        or resources["maximum_active_seconds"] != 21600
        or resources["host_policy"] != BATTERY_POLICY
        or resources["maximum_additional_disk_gib"] != 20
        or resources["minimum_free_gib"] != 10
        or resources["maximum_attempts"] != 3
        or resources["seed_replacement"] is not False
        or resources["early_stopping"] is not False
        or resources["native_transitions"] != 1000000
    ):
        raise ValueError(
            "full model cumulative resources or restoration sample differs"
        )
    if (
        rule["data"]["minimum_training_inputs"] < 10000000
        or rule["data"]["minimum_completed_games"] < 100000
        or rule["data"]["minimum_completed_search_fraction"] < 0.95
    ):
        raise ValueError("full data endpoints were weakened")
    matches = rule["matches"]
    if rule.get("search_optimizations") != {
        "evaluation_cache": True,
        "tactical_generation": True,
        "neural_bounds": False,
        "ordering_hints": False,
    }:
        raise ValueError("full exact search optimization contract differs")
    if (
        matches["neural_pairs"] < 2000
        or sum(matches["external_pairs"]) < 1000
        or len(matches["external_pairs"]) < 3
        or matches["minimum_neural_gain_elo"] < 50
        or matches["minimum_neural_lower_elo_exclusive"] < 0
    ):
        raise ValueError("full strength sample or neural-gain endpoint was weakened")
    return rule


def execute(args):
    root = Path.cwd().resolve()
    dataset, output, finalization = (
        args.dataset.resolve(),
        args.output.resolve(),
        args.finalization.resolve(),
    )
    rule = frozen_rule(args.protocol, args.expected_protocol_sha256)
    if (
        sha(dataset / "DATASET.json") != rule["data"]["dataset_sha256"]
        or sha(finalization) != rule["data"]["finalization_sha256"]
    ):
        raise ValueError(
            "full model data differs from the prospectively frozen identity"
        )
    data = read_json(finalization.read_text())
    manifest = read_json((dataset / "DATASET.json").read_text())
    if (
        data["status"]
        != "passed full original-data finalization and independent reconstruction"
        or data["dataset_sha256"] != rule["data"]["dataset_sha256"]
        or data["protocol_sha256"] != rule["data"]["finalization_protocol_sha256"]
        or data["independent"]["profile"] != "full-data-replay"
        or data["independent"]["independently_rebuilt_splits"] != manifest["splits"]
    ):
        raise ValueError(
            "full independent original-data reconstruction is missing or differs"
        )
    if (
        manifest["splits"]["train"] < 10000000
        or manifest["counts"]["completed_games"] < 100000
        or not manifest["functional_deduplication"]
    ):
        raise ValueError("full original data floors are absent")
    resources = rule["model_campaign"]
    if str(output.relative_to(root)) != resources["output"]:
        raise ValueError("a different output cannot grant a new full model budget")
    if args.resume:
        inputs = read_json((output / "SOURCE_INPUTS.json").read_text())
        commit = inputs["commit"]
    else:
        if subprocess.check_output(["git", "status", "--porcelain"], text=True):
            raise ValueError("commit full model source and protocol first")
        commit = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], text=True
        ).strip()
        inputs = {
            "commit": commit,
            "files": {p: sha(root / p) for p in source_files(root)},
        }
    if sha(__file__) != inputs["files"]["tools/full_learning.py"]:
        raise ValueError("resume full learning with its original archived owner code")
    bindings = {
        "protocol_sha256": args.expected_protocol_sha256,
        "dataset_sha256": rule["data"]["dataset_sha256"],
        "finalization_sha256": rule["data"]["finalization_sha256"],
        "source_commit": commit,
        "workflow_sha256": inputs["files"]["tools/full_learning.py"],
    }
    power = PowerGuard(resources["host_policy"])
    scope = RecoveryScope(
        output,
        bindings,
        resources["maximum_wall_seconds"],
        dataset,
        resources["minimum_free_gib"],
        resources["maximum_additional_disk_gib"],
        resume=args.resume,
        maximum_authorized_seconds=86400,
        maximum_active_seconds=resources["maximum_active_seconds"],
    )
    campaign = None
    try:
        power.start(output)

        def resource_check():
            scope.check()
            power.check()

        if not args.resume:
            atomic(output / "SOURCE_INPUTS.json", inputs)
            (output / "inputs").mkdir()
            shutil.copy2(args.protocol, output / "inputs/PROTOCOL.json")
            shutil.copy2(finalization, output / "inputs/DATA_FINALIZATION.json")
        protocol = output / "inputs/PROTOCOL.json"
        frozen_rule(protocol, args.expected_protocol_sha256)
        attempts = (
            sorted((output / "attempts").glob("attempt-*"))
            if (output / "attempts").exists()
            else []
        )
        if len(attempts) >= resources["maximum_attempts"]:
            raise ValueError("full model maximum recovery attempts used")
        campaign = Campaign(
            output / "attempts" / f"attempt-{len(attempts)+1:03d}",
            {
                "source_commit": commit,
                "global_deadline_unix": scope.deadline,
                "bindings": bindings,
            },
            scope.remaining(),
            absolute_deadline=scope.deadline,
            resource_guard=resource_check,
            maximum_wall_seconds=max(1, scope.deadline - time.time()),
        )
        source = output / "source"
        archive_source(root, source, commit, inputs["files"])

        def run(name, module, arguments):
            resource_check()
            return campaign.run(
                name,
                [sys.executable, "-m", module, *map(str, arguments)],
                scope.remaining(),
                cwd=source,
                wall_timeout=max(1, scope.deadline - time.time()),
            )

        build = output / "build"
        binary = output / "bin/caissa"
        if not (output / "BINARY.json").exists():
            campaign.run(
                "configure",
                [
                    "cmake",
                    "-S",
                    str(source),
                    "-B",
                    str(build),
                    "-G",
                    "Ninja",
                    "-DCMAKE_BUILD_TYPE=Release",
                    "-DCAISSA_NETWORK_WIDTH=64",
                ],
                min(180, scope.remaining()),
            )
            campaign.run(
                "build",
                ["cmake", "--build", str(build), "-j", "2"],
                min(600, scope.remaining()),
            )
            campaign.run(
                "native-correctness",
                ["ctest", "--test-dir", str(build), "--output-on-failure"],
                min(300, scope.remaining()),
            )
            binary.parent.mkdir(exist_ok=True)
            shutil.copy2(build / "caissa", binary)
            atomic(
                output / "BINARY.json",
                {
                    "source_commit": commit,
                    "engine_sha256": sha(binary),
                    "classical_contract": 1,
                    "network_width": 64,
                },
            )
        native = read_json((output / "BINARY.json").read_text())
        if native["engine_sha256"] != sha(binary):
            raise ValueError("frozen full model native executable changed")
        baseline = output / "baselines"
        if not (baseline / "BASELINES.json").exists():
            arguments = [dataset, baseline, "--engine", binary]
            if (baseline / "CONFIG.json").exists():
                arguments += ["--resume"]
            run("original-classical-baselines", "training.baselines", arguments)
        seeds = []
        for seed in rule["training"]["seeds"]:
            folder = output / f"seed{seed}"
            seeds.append(folder)
            finished = False
            if (folder / "SUMMARY.json").exists():
                summary = read_json((folder / "SUMMARY.json").read_text())
                finished = (
                    summary["updates"] == rule["training"]["steps"]
                    and summary["steps"] == rule["training"]["steps"]
                )
            if not finished:
                arguments = [
                    dataset,
                    folder,
                    "--seed",
                    seed,
                    "--steps",
                    rule["training"]["steps"],
                    "--batch",
                    rule["training"]["batch"],
                    "--lr",
                    rule["training"]["lr"],
                    "--outcome-weight",
                    rule["training"]["outcome_weight"],
                    "--threads",
                    rule["training"]["threads"],
                    "--device",
                    rule["training"]["device"],
                    "--checkpoint-every",
                    rule["training"]["checkpoint_every"],
                    "--network-version",
                    rule["network"]["format"],
                    "--width",
                    rule["network"]["width"],
                    "--neural-weight",
                    rule["training"]["neural_weight"],
                    "--baseline-directory",
                    baseline,
                ]
                if (folder / "CHECKPOINTS.json").exists():
                    arguments += ["--resume"]
                run(f"train-{seed}", "training.train", arguments)
        selection = output / "selection"
        if not (selection / "SELECTION.json").exists():
            # Always retain the validation-selected model, including negative
            # learned-loss outcomes. The independent full gate decides pass/fail.
            run(
                "validation-selection",
                "training.select",
                ["--dataset", dataset, "--runs", *seeds, "--output", selection],
            )
        failed = []
        try:
            run(
                "independent-learning",
                "verification.learning",
                [
                    "--dataset",
                    dataset,
                    "--runs",
                    *seeds,
                    "--selection",
                    selection,
                    "--baseline",
                    baseline,
                    "--protocol",
                    protocol,
                    "--require-full",
                    "--output",
                    output / "INDEPENDENT_LEARNING.json",
                ],
            )
        except StageFailure as error:
            observed = read_json((output / "INDEPENDENT_LEARNING.json").read_text())
            if (
                error.record["exit"] != 1
                or observed.get("reason")
                != "learned evaluator did not improve held-out loss over initialization"
                or "independent_seed_observations" not in observed.get("observed", {})
            ):
                raise
            failed.append("G07 held-out learned-loss improvement")
        network, checkpoint = selection / "selected.cai", selection / "selected.pt"
        numerical = output / f"numerical-attempt-{len(attempts)+1:03d}"
        try:
            run(
                "numerical-observations",
                "tools.network_audit",
                [
                    "--engine",
                    binary,
                    "--network",
                    network,
                    "--checkpoint",
                    checkpoint,
                    "--probes",
                    rule["network"]["probes"],
                    "--seed",
                    rule["network"]["probe_seed"],
                    "--maximum-error-cp",
                    rule["network"]["maximum_float_error_cp"],
                    "--max-seconds",
                    min(900, scope.remaining()),
                    "--output",
                    numerical,
                ],
            )
        except StageFailure as error:
            if (
                error.record["exit"] != 1
                or read_json((numerical / "SUMMARY.json").read_text())["status"]
                != "failed-frozen-error-bound"
            ):
                raise
            failed.append("G06 producer numerical endpoint")
        try:
            run(
                "independent-numerical",
                "verification.numerical",
                [
                    numerical,
                    "--engine",
                    binary,
                    "--network",
                    network,
                    "--checkpoint",
                    checkpoint,
                    "--protocol",
                    protocol,
                    "--expected-network-sha256",
                    sha(network),
                    "--expected-checkpoint-sha256",
                    sha(checkpoint),
                    "--require-full",
                    "--max-seconds",
                    min(900, scope.remaining()),
                ],
            )
        except StageFailure as error:
            observed = read_json(
                (campaign.output / "independent-numerical.log").read_text()
            )
            if (
                error.record["exit"] != 1
                or observed.get("reason") != "frozen numerical error bound failed"
                or observed.get("observed", {}).get("probes") != 100000
            ):
                raise
            failed.append("G06 independent numerical endpoint")
        campaign.run(
            "selected-model-restoration",
            [
                str(build / "network_test"),
                str(network),
                str(resources["native_transitions"]),
            ],
            scope.remaining(),
            wall_timeout=max(1, scope.deadline - time.time()),
        )
        scope.check()
        result = {
            "status": (
                "completed planned model domain campaign"
                if not failed
                else "completed planned model domain campaign with failed gates"
            ),
            "failed_domains": failed,
            "source_commit": commit,
            "engine_sha256": sha(binary),
            "network_sha256": sha(network),
            "checkpoint_sha256": sha(checkpoint),
            "dataset_sha256": rule["data"]["dataset_sha256"],
            "protocol_sha256": args.expected_protocol_sha256,
            "seeds": rule["training"]["seeds"],
            "updates_per_seed": rule["training"]["steps"],
            "origin_unix": scope.state["origin_unix"],
            "deadline_unix": scope.deadline,
            "completed_unix": time.time(),
            "test_model_metrics_used_for_selection": False,
            "full_acceptance": False,
            "scope": "Original model learning, numerical and selected-model restoration. Playing strength and all remaining gates are separate.",
        }
        atomic(output / "MODEL_CAMPAIGN.json", result)
        campaign.close(result["status"], result)
        print(json.dumps(result))
        return 2 if failed else 0
    except BaseException as error:
        if campaign is not None:
            campaign.close(
                "failed", {"type": type(error).__name__, "reason": str(error)}
            )
        atomic(
            output / "FAILED.json",
            {
                "type": type(error).__name__,
                "reason": str(error),
                "observed_unix": time.time(),
                "original_deadline_unix": scope.deadline,
                "full_acceptance": False,
            },
        )
        raise
    finally:
        try:
            power.close()
        finally:
            scope.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--protocol", required=True, type=Path)
    parser.add_argument("--expected-protocol-sha256", required=True)
    parser.add_argument("--dataset", required=True, type=Path)
    parser.add_argument("--finalization", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    try:
        return execute(args)
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
                {"status": "failed", "reason": str(error), "full_acceptance": False}
            )
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
