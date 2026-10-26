"""Actual source archives, inherited host exclusion and nested child teardown.

Full-plan and component relationships are checked against rehashed forgeries.
Only the existing small original CI corpus is replayed; no full G07 is claimed.
"""

import argparse
import copy
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from tests.source_binding import repository
from tools.campaign_process import Campaign, StageFailure, atomic
from tools.finalize_corpus import archive_source
from tools.host_lease import ENVIRONMENT, HostLease
from verification.g07_audit import (
    CHECKPOINT,
    DEPLOYED,
    FULL_DATASET,
    OUTPUT,
    RESOURCES,
    contract,
    join_relationships,
)
from verification.learning_bundle import (
    ORIGINAL_MODEL,
    ORIGINAL_PROTOCOL,
    ORIGINAL_SELECTION,
)
from verification.source import PRODUCT, snapshot, verify_archive, verify_checkout


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--catalog", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    project = Path(__file__).resolve().parents[1]
    commit = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], text=True, timeout=5
    ).strip()
    records = []
    rule = {
        "schema": "caissa-g07-live-audit-v1",
        "status": "frozen",
        "source_commit": commit,
        "output": OUTPUT,
        "dataset_sha256": FULL_DATASET,
        "checkpoint_sha256": CHECKPOINT,
        "deployed_network_sha256": DEPLOYED,
        "resources": RESOURCES,
        "data": {"catalog": "not-a-full-catalog.json", "sha256": "1" * 64},
        "learning": {
            "root": "not-full-learning",
            "manifest_sha256": "2" * 64,
            "inputs_sha256": "3" * 64,
        },
    }
    plan = args.output / "PLAN.json"
    atomic(plan, rule)
    contract(plan, sha(plan), commit)
    for case in [
        "renewed-wall",
        "renewed-active",
        "attempts",
        "disk",
        "output",
        "dataset",
        "checkpoint",
        "network",
        "source",
        "unknown-field",
    ]:
        changed = copy.deepcopy(rule)
        if case in {"renewed-wall", "renewed-active", "attempts", "disk"}:
            key = {
                "renewed-wall": "maximum_wall_seconds",
                "renewed-active": "maximum_active_seconds",
                "attempts": "maximum_attempts",
                "disk": "maximum_additional_gib",
            }[case]
            changed["resources"][key] += 1
        elif case == "output":
            changed["output"] += "-reset"
        elif case in {"dataset", "checkpoint", "network"}:
            key = {
                "dataset": "dataset_sha256",
                "checkpoint": "checkpoint_sha256",
                "network": "deployed_network_sha256",
            }[case]
            changed[key] = "0" * 64
        elif case == "source":
            changed["source_commit"] = "0" * 40
        else:
            changed["saved_pass"] = True
        path = args.output / (case + ".json")
        atomic(path, changed)
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "verification.g07_audit",
                str(path),
                "--expected-plan-sha256",
                sha(path),
                "--expected-commit",
                commit,
                "--checkout",
                str(project),
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )
        observed = json.loads(result.stdout)
        assert result.returncode == 1 and observed["full_gate"] is False, (
            case,
            observed,
            result.stderr,
        )
        records.append(
            {
                "case": case,
                "actual_exit": result.returncode,
                "reason": observed["reason"],
            }
        )

    data = json.loads(
        (project / "results/full-data-2026-10-25/independent-data.log").read_text()
    )
    learned = json.loads(
        (
            project / "results/full-model-v3-2026-10-25/INDEPENDENT_LEARNING.json"
        ).read_text()
    )
    data.update(gate="G07", component="data", component_pass=True, full_gate=False)
    learned.update(
        gate="G07",
        component="learning",
        component_pass=True,
        full_gate=False,
        selected_step=2750,
        original_lineage={
            "original_model_campaign_sha256": ORIGINAL_MODEL,
            "original_protocol_sha256": ORIGINAL_PROTOCOL,
            "original_selection_sha256": ORIGINAL_SELECTION,
            "checkpoint_sha256": CHECKPOINT,
            "original_network_sha256": learned["network_sha256"],
            "deployed_network_sha256": DEPLOYED,
            "same_selected_float_checkpoint": True,
            "new_learning_receipt_created": False,
        },
    )
    assert join_relationships(data, learned)["full_gate"] is False
    for case in [
        "different-data",
        "short-corpus",
        "missing-seed",
        "short-checkpoints",
        "test-access",
        "changed-receipt",
        "faked-full-pass",
    ]:
        d, l = copy.deepcopy(data), copy.deepcopy(learned)
        if case == "different-data":
            l["dataset_sha256"] = "0" * 64
        elif case == "short-corpus":
            d["source_pairs"] -= 1
        elif case == "missing-seed":
            l["seeds"] = [17, 73]
        elif case == "short-checkpoints":
            l["all_checkpoints_independently_evaluated"] = 239
        elif case == "test-access":
            l["test_arrays_opened"] = True
        elif case == "changed-receipt":
            l["original_lineage"]["original_model_campaign_sha256"] = "0" * 64
        else:
            d["full_gate"] = True
        try:
            join_relationships(d, l)
        except ValueError as error:
            records.append({"case": case, "reason": str(error), "metadata_only": True})
        else:
            raise AssertionError("G07 join forgery admitted: " + case)

    with tempfile.TemporaryDirectory(prefix="caissa-g07-source-") as folder:
        folder = Path(folder)
        git = folder / "git"
        old_commit = repository(git)
        manifest = {
            "schema": "caissa-source-inputs-v2",
            "policy": PRODUCT,
            "commit": old_commit,
            "files": snapshot(git, old_commit, PRODUCT),
        }
        archive_source(git, folder / "archive", old_commit, manifest["files"])
        subprocess.run(
            ["git", "commit", "--allow-empty", "-qm", "new unrelated checkpoint"],
            cwd=git,
            check=True,
            timeout=5,
        )
        verify_archive(git, folder / "archive", manifest, old_commit)
        try:
            verify_checkout(git, manifest, old_commit, PRODUCT)
        except ValueError:
            records.append(
                {
                    "case": "archive-pins-original-commit-live-checkout-still-rejects-new-head"
                }
            )
        else:
            raise AssertionError("live checkout HEAD rule weakened")
        name = next(iter(manifest["files"]))
        (folder / "archive" / name).write_bytes(b"changed source\n")
        manifest["files"][name] = sha(folder / "archive" / name)
        try:
            verify_archive(git, folder / "archive", manifest, old_commit)
        except ValueError:
            records.append({"case": "rehashed-archive-change-refused-against-Git"})
        else:
            raise AssertionError("changed source archive admitted")

    source_inputs = {
        "schema": "caissa-source-inputs-v2",
        "policy": PRODUCT,
        "commit": commit,
        "files": snapshot(project, commit, PRODUCT),
    }
    archive = args.output / "trusted-source"
    archive_source(project, archive, commit, source_inputs["files"])
    catalog = json.loads(args.catalog.read_text())
    catalog["output"] = str(
        (args.output / "archive-data").resolve().relative_to(project)
    )
    path = args.output / "ARCHIVE_CATALOG.json"
    atomic(path, catalog)
    lease = HostLease(project / "runs")
    campaign = Campaign(
        args.output / "inherited-host", {"scope": "small source/data controls"}, 120
    )
    try:
        script = "from tools.heuristic_study import avoid_decisive_matches;avoid_decisive_matches();print('inherited host admitted')"
        good = campaign.run(
            "real-inherited-lock",
            [sys.executable, "-c", script],
            5,
            pass_fds=(lease.stream.fileno(),),
            env=lease.environment(),
            cwd=project,
        )
        assert good["exit"] == 0
        try:
            campaign.run(
                "closed-descriptor",
                [sys.executable, "-c", script],
                5,
                env=lease.environment(),
                cwd=project,
            )
        except StageFailure:
            records.append({"case": "environment-without-inherited-lock-refused"})
        else:
            raise AssertionError("closed lease descriptor admitted")
        launcher = "import runpy,sys;sys.path.insert(0,sys.argv.pop(1));runpy.run_module('verification.data_catalog',run_name='__main__')"
        result = campaign.run(
            "archived-original-data",
            [
                sys.executable,
                "-P",
                "-c",
                launcher,
                str(archive.resolve()),
                str(path.resolve()),
                "--expected-catalog-sha256",
                sha(path),
                "--expected-commit",
                commit,
                "--input-root",
                str(project),
                "--output",
                str((args.output / "archive-data").resolve()),
                "--diagnostic",
                "--trusted-git",
                str(project),
                "--inherit-process-group",
            ],
            90,
            cwd=project,
            pass_fds=(lease.stream.fileno(),),
            env=lease.environment(),
        )
        observed = json.loads(
            (campaign.output / "archived-original-data.log").read_text()
        )
        assert (
            result["exit"] == 0
            and observed["source_pairs"] == 50
            and observed["component_pass"] is False
        )
        records.append(
            {
                "case": "real-50pair-data-reader-from-frozen-source-under-exclusive-host-lease",
                "observed": observed,
            }
        )
        campaign.close("passed-small-data-source-controls")
    finally:
        campaign.close("closed")
        lease.close()

    pid_path = (args.output / "nested-pid.txt").resolve()
    script = (
        "from pathlib import Path;import os,time;Path("
        + repr(str(pid_path))
        + ").write_text(str(os.getpid()));time.sleep(30)"
    )
    nested = (
        "from tools.campaign_process import Campaign;import sys;from pathlib import Path;c=Campaign(Path("
        + repr(str((args.output / "inner").resolve()))
        + "),{},20);c.run('sleep',[sys.executable,'-c',"
        + repr(script)
        + "],20,new_session=False)"
    )
    outer = Campaign(args.output / "outer", {"scope": "nested timeout cleanup"}, 5)
    try:
        try:
            outer.run("nested", [sys.executable, "-c", nested], 2, cwd=project)
        except StageFailure as error:
            assert error.record["reason"] == "stage-timeout"
        else:
            raise AssertionError("nested timeout unexpectedly passed")
        pid = int(pid_path.read_text())
        for _ in range(30):
            process = subprocess.run(
                ["ps", "-p", str(pid), "-o", "stat="],
                capture_output=True,
                text=True,
                timeout=3,
            )
            if process.returncode or process.stdout.strip().startswith("Z"):
                break
            time.sleep(0.05)
        else:
            raise AssertionError("nested owned reader escaped timeout")
        records.append(
            {"case": "outer-timeout-reaped-inherited-group-grandchild", "pid": pid}
        )
        outer.close("passed-expected-timeout")
    finally:
        outer.close("closed")
    atomic(
        args.output / "CONTROLS.json",
        {
            "status": "passed",
            "cases": records,
            "live_full_G07_executed": False,
            "full_gate": False,
            "full_acceptance": False,
        },
    )
    print(
        json.dumps(
            {
                "status": "passed",
                "plan_cli_rejections": 10,
                "join_rejections": 7,
                "source_controls": 2,
                "real_original_pairs": 50,
                "inherited_host_lock": True,
                "nested_timeout_cleanup": True,
                "full_G07_certified": False,
                "full_acceptance": False,
            }
        )
    )


if __name__ == "__main__":
    main()
