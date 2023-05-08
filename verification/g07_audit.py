"""One bounded live reconstruction of the original data and all training seeds.

Component receipts are joined only after both independent child readers run.
No acquisition, optimization, model selection or match campaign is restarted.
"""

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path

from tools.campaign_process import Campaign, atomic
from tools.finalize_corpus import archive_source
from tools.full_strength import HostGuard
from tools.host_lease import HostLease
from tools.power_guard import POLICY, PowerGuard
from tools.recovery_scope import RecoveryScope
from verification.bundle import digest_text, strict_json
from verification.data_catalog import (
    FULL_DATASET,
    FULL_PREFIX,
    PARENT_DEADLINE,
    contract as data_contract,
    input_path,
    small_document,
)
from verification.draw_history import typed_equal
from verification.learning_bundle import (
    ORIGINAL_MODEL,
    ORIGINAL_PROTOCOL,
    ORIGINAL_SELECTION,
)
from verification.source import (
    PRODUCT,
    require,
    snapshot,
    verify_archive,
    verify_checkout,
)

OUTPUT = "runs/full-g07-audit-v1"
CHECKPOINT = "c76d8e9ef0f2255531bc9085f5d0330a7a4152cf9b21a65ff8aee740ab8b2005"
DEPLOYED = "52d0306143392ad683c3ebb09fe013f34e1f9e2bc44d3aa153b32314207374b7"
ORIGINAL_NETWORK = "c251670ec53ba38a680c16cc6199be48f89cc829dd5483197e6d4b39ac6debf6"
RESOURCES = {
    "maximum_wall_seconds": 28800,
    "maximum_active_seconds": 28800,
    "maximum_data_seconds": 21600,
    "maximum_learning_seconds": 3600,
    "maximum_attempts": 1,
    "maximum_additional_gib": 40,
    "minimum_free_gib": 10,
    "parent_deadline_unix": PARENT_DEADLINE,
}


def contract(path, expected, commit):
    rule = small_document(path, 4 * 1024**2, digest_text(expected))
    require(
        isinstance(rule, dict)
        and set(rule)
        == {
            "schema",
            "status",
            "source_commit",
            "output",
            "dataset_sha256",
            "checkpoint_sha256",
            "deployed_network_sha256",
            "resources",
            "data",
            "learning",
        },
        "G07 audit plan field inventory differs",
    )
    require(
        rule["schema"] == "caissa-g07-live-audit-v1" and rule["status"] == "frozen",
        "G07 audit plan is unsupported or not frozen",
    )
    require(
        rule["source_commit"] == commit
        and len(commit) == 40
        and all(c in "0123456789abcdef" for c in commit),
        "G07 verifier source differs",
    )
    require(
        rule["output"] == OUTPUT, "G07 audit output cannot reset its original scope"
    )
    require(
        typed_equal(rule["resources"], RESOURCES),
        "G07 cumulative resource ceilings differ",
    )
    require(
        rule["dataset_sha256"] == FULL_DATASET
        and rule["checkpoint_sha256"] == CHECKPOINT
        and rule["deployed_network_sha256"] == DEPLOYED,
        "G07 original data or validation-selected deployment identity differs",
    )
    require(
        isinstance(rule["data"], dict) and set(rule["data"]) == {"catalog", "sha256"},
        "G07 data catalog descriptor differs",
    )
    require(
        isinstance(rule["learning"], dict)
        and set(rule["learning"]) == {"root", "manifest_sha256", "inputs_sha256"},
        "G07 learning catalog descriptor differs",
    )
    for value in [
        rule["data"]["sha256"],
        rule["learning"]["manifest_sha256"],
        rule["learning"]["inputs_sha256"],
    ]:
        digest_text(value)
    from verification.source import relative_path

    relative_path(rule["data"]["catalog"])
    relative_path(rule["learning"]["root"])
    return rule


def join_relationships(data, learning):
    for component, report in [("data", data), ("learning", learning)]:
        require(
            report.get("status") == "passed"
            and report.get("gate") == "G07"
            and report.get("component") == component
            and report.get("component_pass") is True
            and report.get("full_gate") is False
            and report.get("full_acceptance") is False,
            "G07 component is missing, failed or falsely promoted: " + component,
        )
        require(
            report.get("dataset_sha256") == FULL_DATASET,
            "G07 components do not share the original dataset",
        )
    splits = data.get("independently_rebuilt_splits", {})
    require(
        data.get("profile") == "full-data-replay"
        and data.get("original_acquisition_status") == "failed-preserved"
        and data.get("recovery_protocol_sha256") == FULL_PREFIX
        and type(data.get("source_pairs")) is int
        and data["source_pairs"] == 114791
        and type(data.get("completed_games")) is int
        and data["completed_games"] >= 100000
        and type(splits.get("train")) is int
        and splits["train"] >= 10000000,
        "G07 data component lacks the complete original corpus reconstruction",
    )
    require(
        learning.get("profile") == "full-learning-domain"
        and typed_equal(learning.get("seeds"), [17, 41, 73])
        and type(learning.get("all_checkpoints_independently_evaluated")) is int
        and learning["all_checkpoints_independently_evaluated"] == 240
        and type(learning.get("validation_positions_per_checkpoint")) is int
        and learning["validation_positions_per_checkpoint"] == 8192
        and type(learning.get("selected_seed")) is int
        and learning["selected_seed"] == 73
        and type(learning.get("selected_step")) is int
        and learning["selected_step"] == 2750
        and learning.get("test_arrays_opened") is False
        and learning.get("network_sha256") == ORIGINAL_NETWORK,
        "G07 learning component did not replay every original seed/checkpoint",
    )
    lineage = learning.get("original_lineage", {})
    require(
        lineage.get("original_model_campaign_sha256") == ORIGINAL_MODEL
        and lineage.get("original_protocol_sha256") == ORIGINAL_PROTOCOL
        and lineage.get("original_selection_sha256") == ORIGINAL_SELECTION
        and lineage.get("checkpoint_sha256") == CHECKPOINT
        and lineage.get("original_network_sha256") == ORIGINAL_NETWORK
        and lineage.get("deployed_network_sha256") == DEPLOYED
        and lineage.get("same_selected_float_checkpoint") is True
        and lineage.get("new_learning_receipt_created") is False,
        "G07 join replaced the original receipt or selected float lineage",
    )
    # This function checks relationships only. A caller must run both readers
    # within one owned campaign before it may certify the complete gate.
    return {
        "dataset_sha256": FULL_DATASET,
        "checkpoint_sha256": CHECKPOINT,
        "original_model_campaign_sha256": ORIGINAL_MODEL,
        "same_original_data_and_selected_float": True,
        "full_gate": False,
        "full_acceptance": False,
    }


def strength_settled(checkout):
    """Do not steal the brief lock handoff between frozen strength phases."""
    runs = Path(checkout) / "runs"
    external = runs / "full-external-strength-v4"
    complete = external / "STRENGTH_CAMPAIGN.json"
    usage = external / "ACTIVE_USAGE.json"
    if complete.is_file() and usage.is_file():
        receipt, ledger = strict_json(complete.read_bytes()), strict_json(
            usage.read_bytes()
        )
        if receipt.get("scope_closed") is True and ledger.get("closed") is True:
            return True
    # A genuinely exhausted failed strength domain must not block independent
    # verification forever. A recoverable failure retains priority instead.
    for folder, combined in [
        (external, False),
        (runs / "full-neural-strength-v4-wall-recovery-v1", True),
    ]:
        usage, scope = folder / "ACTIVE_USAGE.json", folder / "SCOPE.json"
        if (
            not usage.is_file()
            or not scope.is_file()
            or not list(folder.glob("FAILED*.json"))
        ):
            continue
        ledger, limits = strict_json(usage.read_bytes()), strict_json(
            scope.read_bytes()
        )
        if ledger.get("closed") is not True:
            continue
        attempts = len(list((folder / "attempts").glob("attempt-*")))
        if combined:
            attempts += limits["bindings"]["original_attempts"]
        active = ledger.get(
            "combined_active_seconds" if combined else "active_seconds", 0
        )
        if time.time() >= limits["deadline_unix"] or attempts >= 3 or active >= 43200:
            return True
    return False


def execute(plan, expected, checkout, commit, *, archived_source=False):
    checkout = Path(checkout).resolve()
    rule = contract(plan, expected, commit)
    output = checkout / OUTPUT
    require(
        not output.exists(),
        "G07 original audit scope already exists; no reset or rerun",
    )
    require(
        time.time() + RESOURCES["maximum_wall_seconds"] <= PARENT_DEADLINE,
        "G07 audit cannot fit the original parent deadline",
    )
    require(
        strength_settled(checkout),
        "frozen strength pipeline is not settled; preserve its handoff priority",
    )
    lease = HostLease(checkout / "runs")
    scope = campaign = power = None
    closed = False
    try:
        source_inputs = {
            "schema": "caissa-source-inputs-v2",
            "policy": PRODUCT,
            "commit": commit,
            "files": snapshot(checkout, commit, PRODUCT),
        }
        code = Path(__file__).resolve().parents[1]
        if archived_source:
            verify_archive(checkout, code, source_inputs, commit, PRODUCT)
        else:
            verify_checkout(checkout, source_inputs, commit, PRODUCT)
            require(code == checkout, "launch G07 from its explicitly trusted checkout")
        scope = RecoveryScope(
            output,
            {
                "plan_sha256": expected,
                "source_commit": commit,
                "dataset_sha256": FULL_DATASET,
            },
            28800,
            output / "empty-input-accounting",
            10,
            40,
            maximum_authorized_seconds=43200,
            maximum_active_seconds=28800,
        )
        power = PowerGuard(POLICY if sys.platform == "darwin" else None)
        power.start(output)
        host = HostGuard(output, scope, power)

        def guard():
            lease.check()
            host.check()

        guard()
        catalog = input_path(checkout, rule["data"]["catalog"])
        data_rule = data_contract(catalog, rule["data"]["sha256"], commit)
        require(
            data_rule["output"] == OUTPUT + "/data"
            and data_rule["dataset_sha256"] == FULL_DATASET,
            "G07 data child is outside its frozen scope or dataset",
        )
        learning = input_path(checkout, rule["learning"]["root"])
        require(
            not output.is_relative_to(learning) and not learning.is_relative_to(output),
            "G07 audit must preserve the original learning evidence",
        )
        atomic(output / "PLAN.json", rule)
        atomic(output / "SOURCE_INPUTS.json", source_inputs)
        archive_source(checkout, output / "source", commit, source_inputs["files"])
        campaign = Campaign(
            output / "execution",
            {"gate": "G07", "plan_sha256": expected, "source_commit": commit},
            scope.remaining(),
            absolute_deadline=scope.deadline,
            resource_guard=guard,
        )
        launcher = "import runpy,sys;sys.path.insert(0,sys.argv.pop(1));runpy.run_module(sys.argv.pop(1),run_name='__main__')"

        def run(stage, module, args, maximum):
            guard()
            return campaign.run(
                stage,
                [
                    sys.executable,
                    "-P",
                    "-X",
                    "pycache_prefix=" + str(output / "runtime-cache"),
                    "-c",
                    launcher,
                    str(output / "source"),
                    module,
                    *map(str, args),
                ],
                min(maximum, scope.remaining()),
                maximum_output_bytes=4 * 1024**2,
                cwd=checkout,
                pass_fds=(lease.stream.fileno(),),
                env=lease.environment(),
            )

        run(
            "data",
            "verification.data_catalog",
            [
                catalog,
                "--expected-catalog-sha256",
                rule["data"]["sha256"],
                "--expected-commit",
                commit,
                "--input-root",
                checkout,
                "--output",
                output / "data",
                "--trusted-git",
                checkout,
                "--inherit-process-group",
            ],
            21600,
        )
        data = strict_json((output / "execution/data.log").read_bytes())
        require(
            typed_equal(data, strict_json((output / "data/DATA.json").read_bytes())),
            "G07 live data reader and retained artifact disagree",
        )
        run(
            "learning",
            "verification.learning_bundle",
            [
                learning,
                "--expected-manifest-sha256",
                rule["learning"]["manifest_sha256"],
                "--expected-inputs-sha256",
                rule["learning"]["inputs_sha256"],
                "--maximum-seconds",
                min(3600, scope.remaining()),
                "--output",
                output / "learning",
                "--inherit-process-group",
            ],
            3600,
        )
        learned = strict_json((output / "execution/learning.log").read_bytes())
        require(
            typed_equal(
                learned, strict_json((output / "learning/LEARNING.json").read_bytes())
            ),
            "G07 live learning reader and retained artifact disagree",
        )
        relationships = join_relationships(data, learned)
        guard()
        result = {
            "schema": "caissa-full-g07-live-replay-v1",
            "status": "passed",
            "gate": "G07",
            "full_gate": True,
            "full_acceptance": False,
            "source_commit": commit,
            "plan_sha256": expected,
            "relationships": relationships,
            "live_components_executed": ["data", "learning"],
            "origin_unix": scope.state["origin_unix"],
            "deadline_unix": scope.deadline,
            "completed_unix": time.time(),
            "scope_closed": True,
            "components": {
                name: {
                    "path": name + "/" + file,
                    "sha256": hashlib.sha256(
                        (output / name / file).read_bytes()
                    ).hexdigest(),
                }
                for name, file in [("data", "DATA.json"), ("learning", "LEARNING.json")]
            },
            "original_learning_receipt_unchanged": True,
            "other_gates_and_release_audit_required": True,
        }
        campaign.close("passed-live-G07-reconstruction", result)
        scope.close()
        closed = True
        atomic(output / "G07.json", result)
        return result
    except BaseException as error:
        if campaign is not None:
            campaign.close(
                "failed", {"type": type(error).__name__, "reason": str(error)}
            )
        if scope is not None:
            atomic(
                output / "FAILED.json",
                {
                    "type": type(error).__name__,
                    "reason": str(error),
                    "unix": time.time(),
                    "full_gate": False,
                    "full_acceptance": False,
                },
            )
        raise
    finally:
        try:
            if power is not None:
                power.close()
        finally:
            if scope is not None and not closed:
                scope.close()
            lease.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("plan", type=Path)
    parser.add_argument("--expected-plan-sha256", required=True)
    parser.add_argument("--checkout", type=Path, required=True)
    parser.add_argument("--expected-commit", required=True)
    parser.add_argument("--archived-source", action="store_true")
    args = parser.parse_args()
    try:
        result = execute(
            args.plan,
            args.expected_plan_sha256,
            args.checkout,
            args.expected_commit,
            archived_source=args.archived_source,
        )
        print(json.dumps(result))
        return 0
    except (ValueError, KeyError, TypeError, OSError, RuntimeError) as error:
        print(
            json.dumps(
                {
                    "status": "rejected",
                    "reason": str(error),
                    "full_gate": False,
                    "full_acceptance": False,
                }
            )
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
