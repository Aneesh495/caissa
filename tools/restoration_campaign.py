"""One persistent, source-frozen full G02 scope with retained attempts."""

import argparse
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

from tools.campaign_process import Campaign, atomic
from tools.finalize_corpus import archive_source
from tools.heuristic_study import avoid_decisive_matches
from tools.power_guard import BATTERY_POLICY, PowerGuard
from tools.recovery_scope import RecoveryScope
from verification.restoration import PROFILE_SHA256, digest
from verification.source import PRODUCT, inventory

OUTPUT = Path("runs/restoration-full-v1")
PARENT_PROJECT_DEADLINE = 1793150297.974828


def native_inputs(root, commit):
    return {
        blob.name: blob.identity
        for blob in inventory(root, commit, PRODUCT)
        if blob.name == "CMakeLists.txt"
        or blob.name.startswith(("src/", "include/", "apps/"))
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--engine", type=Path, required=True)
    parser.add_argument("--expected-engine-sha256", required=True)
    parser.add_argument("--engine-source-commit", required=True)
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    avoid_decisive_matches()
    root = Path.cwd().resolve()
    output = root / OUTPUT
    profile = root / "config/restoration-v1.json"
    if digest(profile) != PROFILE_SHA256:
        raise ValueError("full restoration prospective profile changed")
    rule = json.loads(profile.read_text())
    if (output / "RESTORATION_CAMPAIGN.json").exists():
        raise ValueError("full restoration scope already completed and closed")
    if args.resume:
        inputs = json.loads((output / "SOURCE_INPUTS.json").read_text())
        commit = inputs["commit"]
    else:
        if subprocess.check_output(
            ["git", "status", "--porcelain"], text=True, timeout=10
        ):
            raise ValueError(
                "commit restoration source and controls before full observations"
            )
        commit = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], text=True, timeout=5
        ).strip()
        inputs = {
            "commit": commit,
            "files": {
                blob.name: digest(root / blob.name)
                for blob in inventory(root, commit, PRODUCT)
            },
        }
    if digest(__file__) != inputs["files"]["tools/restoration_campaign.py"]:
        raise ValueError("resume restoration only with the original archived owner")
    origin_native = native_inputs(root, args.engine_source_commit)
    if native_inputs(root, commit) != origin_native:
        raise ValueError(
            "declared compiled native inputs differ from frozen producer source"
        )
    if not args.resume and (
        not args.engine.is_file()
        or args.engine.stat().st_size > 128 * 1024 * 1024
        or digest(args.engine) != args.expected_engine_sha256
        or digest(root / "results/precision-v4-2026-10-25/selected-v4.cai")
        != rule["network_sha256"]
    ):
        raise ValueError(
            "full restoration supplied runtime or model is not its pinned actor"
        )
    bindings = {
        "source_commit": commit,
        "engine_source_commit": args.engine_source_commit,
        "engine_sha256": args.expected_engine_sha256,
        "network_sha256": rule["network_sha256"],
        "profile_sha256": PROFILE_SHA256,
        "workflow_sha256": inputs["files"]["tools/restoration_campaign.py"],
        "parent_project_deadline_unix": PARENT_PROJECT_DEADLINE,
    }
    if (
        not args.resume
        and time.time() + rule["maximum_campaign_seconds"] > PARENT_PROJECT_DEADLINE
    ):
        raise TimeoutError(
            "full restoration would exceed the original parent project ceiling"
        )
    scope = RecoveryScope(
        output,
        bindings,
        rule["maximum_campaign_seconds"],
        root / "runs/searched-full-model-v3",
        rule["minimum_free_bytes"] / 1024**3,
        rule["maximum_additional_disk_bytes"] / 1024**3,
        resume=args.resume,
        maximum_authorized_seconds=21600,
        maximum_active_seconds=rule["maximum_campaign_seconds"],
    )
    power = PowerGuard(BATTERY_POLICY)
    campaign = None
    try:
        power.start(output)
        if not args.resume:
            atomic(output / "SOURCE_INPUTS.json", inputs)
            (output / "inputs").mkdir()
            (output / "bin").mkdir()
            shutil.copyfile(args.engine, output / "bin/caissa")
            (output / "bin/caissa").chmod(0o755)
            shutil.copyfile(
                root / "results/precision-v4-2026-10-25/selected-v4.cai",
                output / "inputs/selected.cai",
            )
            shutil.copyfile(profile, output / "inputs/PROFILE.json")
            atomic(
                output / "NATIVE_INPUTS.json",
                {
                    "declared_compiled_source": args.engine_source_commit,
                    "same_native_blobs_as_owner_source": commit,
                    "native_git_blobs": origin_native,
                    "engine_sha256": args.expected_engine_sha256,
                },
            )
        engine, network = output / "bin/caissa", output / "inputs/selected.cai"
        if (
            digest(engine) != args.expected_engine_sha256
            or digest(network) != rule["network_sha256"]
        ):
            raise ValueError(
                "full restoration immutable runtime or selected model changed"
            )
        attempts = sorted((output / "attempts").glob("attempt-*"))
        if len(attempts) >= rule["maximum_attempts"]:
            raise ValueError("full restoration original attempt ceiling exhausted")
        source = output / "source"
        archive_source(root, source, commit, inputs["files"])

        def resource_check():
            scope.check()
            power.check()

        campaign = Campaign(
            output / "attempts" / f"attempt-{len(attempts)+1:03d}",
            bindings,
            scope.remaining(),
            absolute_deadline=min(scope.deadline, PARENT_PROJECT_DEADLINE),
            resource_guard=resource_check,
        )
        prior = []
        for attempt in attempts:
            candidate = attempt / "producer"
            if (candidate / "SUMMARY.json").exists():
                prior.append(candidate)
        producer = prior[0] if prior else campaign.output / "producer"
        if not prior:
            campaign.run(
                "observe-million",
                [
                    sys.executable,
                    "-m",
                    "tools.restoration",
                    "--engine",
                    str(engine),
                    "--network",
                    str(network),
                    "--profile",
                    str(output / "inputs/PROFILE.json"),
                    "--expected-profile-sha256",
                    PROFILE_SHA256,
                    "--source-commit",
                    commit,
                    "--pairs",
                    str(rule["transitions"]),
                    "--maximum-seconds",
                    str(rule["maximum_producer_seconds"]),
                    "--output",
                    str(producer),
                ],
                min(rule["maximum_producer_seconds"], scope.remaining()),
                cwd=source,
            )
        summary = json.loads((producer / "SUMMARY.json").read_text())
        independent = campaign.output / "independent"
        campaign.run(
            "independent-million",
            [
                sys.executable,
                "-m",
                "verification.restoration",
                "--observations",
                str(producer / "observations.jsonl"),
                "--summary",
                str(producer / "SUMMARY.json"),
                "--config",
                str(producer / "CONFIG.json"),
                "--engine",
                str(engine),
                "--network",
                str(network),
                "--profile",
                str(output / "inputs/PROFILE.json"),
                "--expected-engine-sha256",
                args.expected_engine_sha256,
                "--expected-network-sha256",
                rule["network_sha256"],
                "--expected-profile-sha256",
                PROFILE_SHA256,
                "--expected-observations-sha256",
                summary["observations_sha256"],
                "--output",
                str(independent),
                "--mode",
                "full",
                "--maximum-seconds",
                str(min(rule["maximum_independent_seconds"], scope.remaining())),
            ],
            min(rule["maximum_independent_seconds"], scope.remaining()),
            cwd=source,
        )
        verified = json.loads((independent / "RESTORATION.json").read_text())
        if (
            verified.get("full_gate") is not True
            or verified.get("pairs") != rule["transitions"]
        ):
            raise ValueError(
                "full restoration independent required sample did not pass"
            )
        result = {
            "status": "completed full restoration sample",
            **bindings,
            "pairs": verified["pairs"],
            "producer": str(producer.relative_to(output)),
            "independent": str(independent.relative_to(output)),
            "observations_sha256": summary["observations_sha256"],
            "independent_sha256": digest(independent / "RESTORATION.json"),
            "origin_unix": scope.state["origin_unix"],
            "deadline_unix": scope.deadline,
            "completed_unix": time.time(),
            "full_gate": True,
            "full_acceptance": False,
        }
        atomic(output / "RESTORATION_CAMPAIGN.json", result)
        campaign.close("passed", result)
        print(json.dumps(result))
    except BaseException as error:
        if campaign is not None:
            campaign.close("failed", {"error": repr(error), "full_acceptance": False})
        atomic(
            output / "FAILED.json",
            {
                "error": repr(error),
                "unix": time.time(),
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


if __name__ == "__main__":
    main()
