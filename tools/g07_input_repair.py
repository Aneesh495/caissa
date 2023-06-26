"""One explicitly authorized input repair, charged to the original ceilings.

The failed preparation, its archived reader and all partial files remain intact.
No games, optimizer steps, selection or original model receipts are rewritten.
"""

import argparse
import hashlib
import json
import shutil
import subprocess
import time
from pathlib import Path

from tools.campaign_process import atomic
from tools.g07_inputs import learning_catalog, metadata_sha
from tools.heuristic_study import avoid_decisive_matches
from tools.host_lease import HostLease
from tools.power_guard import POLICY, PowerGuard
from tools.recovery_scope import tree_bytes
from verification.bundle import strict_json
from verification.data_catalog import contract as data_contract
from verification.g07_audit import OUTPUT, RESOURCES, contract, strength_settled
from verification.source import require

ORIGINAL = "runs/full-g07-inputs-v1"
AUTHORIZATION = "work/g12-browser-component-development-v1/AUTHORIZATION.json"


def execute(checkout, authorization_sha256):
    started, wall = time.monotonic(), time.time()
    checkout = Path(checkout).resolve()
    avoid_decisive_matches(checkout / "runs")
    require(strength_settled(checkout), "original strength pipeline is not settled")
    original = checkout / ORIGINAL
    authorization = checkout / AUTHORIZATION
    require(
        metadata_sha(authorization) == authorization_sha256,
        "repair authorization identity differs",
    )
    auth = strict_json(authorization.read_bytes())
    require(
        auth.get("human_answer") == "Approve one repair attempt each"
        and auth.get("additional_attempts")
        == {"G07_input_preparation": 1, "G12_hosted_browser_execution": 1}
        and auth.get("wall_deadlines_unchanged") is True
        and auth.get("cumulative_active_and_disk_caps_unchanged") is True,
        "explicit one-attempt repair authorization required",
    )
    pins = {
        name: metadata_sha(original / name)
        for name in [
            "SCOPE.json",
            "FAILED.json",
            "ACTIVE_USAGE.json",
            "SOURCE_INPUTS.json",
            "data-catalog/CATALOG.json",
        ]
    }
    scope = strict_json((original / "SCOPE.json").read_bytes())
    usage = strict_json((original / "ACTIVE_USAGE.json").read_bytes())
    require(
        usage.get("closed") is True
        and scope["maximum_active_seconds"] == 3600
        and scope["maximum_additional_bytes"] == 20 * 1024**3
        and scope["minimum_free_bytes"] == 10 * 1024**3,
        "original failed input scope differs",
    )
    original_active = usage["active_seconds"]
    require(
        type(original_active) in (int, float)
        and 0 <= original_active < 3600
        and time.time() < scope["deadline_unix"],
        "original input time ceiling exhausted",
    )
    commit = scope["bindings"]["source_commit"]
    catalog = original / "data-catalog/CATALOG.json"
    data_contract(catalog, pins["data-catalog/CATALOG.json"], commit)
    output = original / "repair-001"
    require(not output.exists(), "the single approved input repair already exists")
    lease = HostLease(checkout / "runs")
    power = PowerGuard(POLICY)
    output.mkdir()
    atomic(
        output / "REPAIR_SCOPE.json",
        {
            "schema": "caissa-authorized-input-repair-v1",
            "authorization_sha256": authorization_sha256,
            "producer_source_commit": subprocess.check_output(
                ["git", "rev-parse", "HEAD"], cwd=checkout, text=True, timeout=5
            ).strip(),
            "independent_reader_source_commit": commit,
            "original_pins": pins,
            "deadline_unix": scope["deadline_unix"],
            "maximum_combined_active_seconds": 3600,
            "maximum_combined_additional_bytes": 20 * 1024**3,
            "minimum_free_bytes": 10 * 1024**3,
            "original_active_seconds": original_active,
            "combined_attempts": 2,
            "original_failed_scope_unchanged": True,
        },
    )

    def guard():
        lease.check()
        power.check()
        elapsed = time.monotonic() - started
        require(
            time.time() < scope["deadline_unix"] and original_active + elapsed < 3600,
            "original combined input wall/active ceiling exhausted",
        )
        require(
            shutil.disk_usage(original).free >= 10 * 1024**3
            and tree_bytes(original) - scope["initial_data_bytes"] <= 20 * 1024**3,
            "original combined input disk ceiling exhausted",
        )
        atomic(
            output / "ACTIVE_USAGE.json",
            {
                "original_active_seconds": original_active,
                "repair_active_seconds": elapsed,
                "combined_active_seconds": original_active + elapsed,
                "closed": False,
            },
        )

    try:
        power.start(output)
        guard()
        learning = learning_catalog(checkout, output / "learning", guard)
        plan = {
            "schema": "caissa-g07-live-audit-v1",
            "status": "frozen",
            "source_commit": commit,
            "output": OUTPUT,
            "dataset_sha256": "f09cdec986858c5b1aa80b3c97aaa4d825be892fc94e16ac5d835bc3d709f0ce",
            "checkpoint_sha256": "c76d8e9ef0f2255531bc9085f5d0330a7a4152cf9b21a65ff8aee740ab8b2005",
            "deployed_network_sha256": "52d0306143392ad683c3ebb09fe013f34e1f9e2bc44d3aa153b32314207374b7",
            "resources": RESOURCES,
            "data": {
                "catalog": str(catalog.relative_to(checkout)),
                "sha256": pins["data-catalog/CATALOG.json"],
            },
            "learning": {
                key: str(Path(value).relative_to(checkout)) if key == "root" else value
                for key, value in learning.items()
                if key in {"root", "manifest_sha256", "inputs_sha256"}
            },
        }
        path = output / "PLAN.json"
        atomic(path, plan)
        contract(path, metadata_sha(path), commit)
        guard()
        for name, digest in pins.items():
            require(
                metadata_sha(original / name) == digest,
                "original failed input evidence changed: " + name,
            )
        result = {
            "status": "prepared by explicitly authorized repair",
            "plan": str(path),
            "plan_sha256": metadata_sha(path),
            "catalog_sha256": pins["data-catalog/CATALOG.json"],
            "original_reader_commit": commit,
            "full_G07_certified": False,
            "original_failed_scope_unchanged": True,
        }
        atomic(output / "PREPARATION_REPAIR.json", result)
        return result
    except BaseException as error:
        atomic(
            output / "FAILED.json",
            {
                "reason": str(error),
                "type": type(error).__name__,
                "unix": time.time(),
                "full_G07_certified": False,
            },
        )
        raise
    finally:
        elapsed = time.monotonic() - started
        atomic(
            output / "ACTIVE_USAGE.json",
            {
                "original_active_seconds": original_active,
                "repair_active_seconds": elapsed,
                "combined_active_seconds": original_active + elapsed,
                "closed": True,
            },
        )
        power.close()
        lease.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--checkout", type=Path, required=True)
    parser.add_argument("--authorization-sha256", required=True)
    args = parser.parse_args()
    print(json.dumps(execute(args.checkout, args.authorization_sha256)))


if __name__ == "__main__":
    main()
