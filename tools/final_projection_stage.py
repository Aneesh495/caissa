"""Unexecuted single-entry stage bridge for a future admitted metadata owner.

No CLI, authority, scope, owner, fixture or test is created on import. A real
admitted owner must initialize the exact lease, campaign and shared quota first.
This bridge cannot renew authority or replace the missing outer owner.
"""

import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import time

from tools.campaign_process import Campaign, StageFailure
from tools.host_lease import HostLease
from tools.parallel_storage_quota import Quota
from verification.final_projection_entry import ROOT, TOKEN_ENV, admit, private_bytes, require, strict_json


class ProjectionQuota(Quota):
    """Exact prospective metadata destinations, with no fixture writer."""

    def classify(self, target, *, replacement=False):
        target = Path(target).absolute()
        require(target == target.resolve() and target.is_relative_to(self.output),
                "projection parent writer escaped its admitted work directory")
        name = str(target.relative_to(self.output))
        parent = {"OWNER_STARTED.json", "ENTRY_ADMISSION.json", "OWNER_RESULT.json",
                  "OWNER_RESULT.json.tmp", "FAILED-owner.json", "FAILED-owner.json.tmp"}
        stage = {"WRITER.lock", "CONFIG.json", "CONFIG.json.tmp", "COMMANDS.jsonl",
                 "PROGRESS.json", "PROGRESS.json.tmp", "CAMPAIGN.json", "CAMPAIGN.json.tmp",
                 "full-entry.log", "full-entry.json", "full-entry.json.tmp"}
        require(name in parent or name.startswith("entry-stage/")
                and name.removeprefix("entry-stage/") in stage,
                "unknown projection parent output")
        if name in {"OWNER_STARTED.json", "ENTRY_ADMISSION.json"}:
            require(not target.exists(), "projection owner or entry admission is already consumed")
        return "control", name


def run_entry(scope_name, expected_scope_sha256, *, campaign, quota, lease):
    """One prospective real stage, never a direct or alternate verifier call."""
    scope, scope_sha, relative_work = admit(scope_name, expected_scope_sha256)
    work = ROOT / relative_work
    require(type(campaign) is Campaign and type(quota) is ProjectionQuota
            and type(lease) is HostLease, "real owned campaign, projection quota and lease required")
    require(campaign.output == work / "entry-stage" and campaign.sequence == 0
            and not campaign.closed and campaign.wall_deadline <= scope["deadline_unix"]
            and campaign.config["scope_sha256"] == scope_sha
            and campaign.config["source_commit"] == scope["product_commit"]
            and callable(campaign.resource_guard), "fresh bounded single-stage campaign required")
    require(quota.output == work and quota.ledger == work / "WRITE_USAGE.json"
            and quota.spec["scope_sha256"] == scope_sha
            and quota.spec["deadline_unix"] == scope["deadline_unix"]
            and quota.spec["control_bytes"] == scope["control_bytes"]
            and quota.spec["emergency_control_bytes"] == scope["emergency_control_bytes"]
            and quota.spec["data_bytes"] == 0 and quota.spec["reserve_bytes"] == 128000000
            and quota.old is not None, "installed shared metadata quota differs from admission")
    state = quota.read()
    require(state["scope_sha256"] == scope_sha and state["closed"] is False
            and state.get("failure") is None, "projection storage ledger is failed or closed")
    owner = strict_json(private_bytes(relative_work + "OWNER_STARTED.json", 8192))
    require(owner["schema"] == "caissa-final-projection-owner-started-v1"
            and owner["scope_sha256"] == scope_sha and type(owner["owner_pid"]) is int
            and owner["owner_pid"] == os.getpid()
            and type(owner["owner_start"]) is int and owner["owner_start"] == 1,
            "actual once-only owner start is missing or mismatched")
    require(not (work / "ENTRY_ADMISSION.json").exists(), "entry admission already consumed")
    require(scope["python_command"] == sys.executable,
            "parent must preserve the admitted virtual environment command")
    maximum_output = scope["maximum_entry_output_bytes"]
    require(type(maximum_output) is int and 1024 <= maximum_output <= 2 * 1024**2,
            "finite metered entry output bound required")
    require(type(scope["expected_entry_exit"]) is int and scope["expected_entry_exit"] == 2
            and scope["expected_G14_classification"] in {"verified", "unverified"},
            "frozen failed requirements must preserve the actual nonpassing exit")
    require(lease.path == ROOT / "runs/TIMED_STRENGTH.lock", "parent host lease path differs")
    lease.check()
    campaign.resource_guard()
    remaining = min(scope["maximum_entry_seconds"], scope["deadline_unix"] - time.time(),
                    campaign.deadline - time.monotonic())
    require(remaining > 0, "parent entry deadline exhausted before token creation")
    token = {"scope_sha256": scope_sha, "nonce": scope["entry_nonce"],
             "owner_pid": os.getpid(), "invocation": 1}
    raw = json.dumps(token, sort_keys=True, separators=(",", ":")).encode()
    require(0 < len(raw) <= 512, "entry token exceeds one bounded atomic pipe write")
    record = {**token, "schema": "caissa-final-entry-parent-admission-v1",
              "token_sha256": hashlib.sha256(raw).hexdigest()}
    record_raw = json.dumps(record, sort_keys=True, separators=(",", ":")).encode()
    require(len(record_raw) <= 8192, "parent admission record exceeds its private bound")
    with (work / "ENTRY_ADMISSION.json").open("xb") as stream:
        stream.write(record_raw)
        stream.flush()
        os.fsync(stream.fileno())
    recorded = private_bytes(relative_work + "ENTRY_ADMISSION.json", 8192)
    require(recorded == record_raw, "parent admission record mode or bytes differ")
    read_fd, write_fd = os.pipe()
    previous_popen = subprocess.Popen
    child = [None]
    attempts = [0]
    command = [scope["python_command"], "-B", "-P",
               str(ROOT / "verification/final_projection_entry.py"),
               "--scope", scope_name, "--expected-scope-sha256", scope_sha]
    environment = {**lease.environment(), TOKEN_ENV: str(read_fd)}
    descriptors = (lease.stream.fileno(), read_fd)

    def spawn(actual, *args, **kwargs):
        require(actual == command and not args and attempts[0] == 0
                and set(kwargs) == {"stdin", "stdout", "stderr", "bufsize", "start_new_session",
                                    "cwd", "pass_fds", "env"}
                and kwargs["stdin"] == subprocess.DEVNULL and kwargs["stdout"] == subprocess.PIPE
                and kwargs["stderr"] == subprocess.STDOUT and kwargs["bufsize"] == 0
                and kwargs["start_new_session"] is True and Path(kwargs["cwd"]) == ROOT
                and kwargs["pass_fds"] == descriptors and kwargs["env"] == environment,
                "projection parent command, descriptors, ownership or start count differs")
        attempts[0] += 1
        child[0] = previous_popen(actual, **kwargs)
        return child[0]

    try:
        require(os.write(write_fd, raw) == len(raw), "parent token pipe write was incomplete")
        os.close(write_fd)
        write_fd = None
        subprocess.Popen = spawn
        try:
            receipt = campaign.run("full-entry", command, remaining,
                                   maximum_output_bytes=maximum_output, cwd=ROOT,
                                   wall_timeout=remaining, pass_fds=descriptors, env=environment)
        except StageFailure as error:
            receipt = error.record
            require(receipt["exit"] == 2 and receipt["reason"] == "nonzero-exit",
                    "projection stage failed instead of returning a valid nonpassing report")
    finally:
        subprocess.Popen = previous_popen
        os.close(read_fd)
        if write_fd is not None:
            os.close(write_fd)
    require(attempts[0] == campaign.sequence == 1 and child[0] is not None
            and child[0].returncode == receipt["exit"] == 2
            and receipt["discarded_output_bytes"] == 0 and not receipt["cleanup_warnings"],
            "actual projection exit, count, output or cleanup differs")
    try:
        os.killpg(child[0].pid, 0)
    except ProcessLookupError:
        pass
    else:
        raise ValueError("projection entry group remains after reaping")
    log = campaign.output / "full-entry.log"
    require(not log.is_symlink() and stat.S_ISREG(log.stat().st_mode)
            and stat.S_IMODE(log.stat().st_mode) == 0o600 and log.stat().st_nlink == 1
            and log.stat().st_size <= maximum_output,
            "projection stage log is missing or excessive")
    output = log.read_bytes()
    require(len(output) == receipt["retained_output_bytes"]
            and hashlib.sha256(output).hexdigest() == receipt["log_sha256"],
            "actual projection log differs from stage receipt")
    report = strict_json(output)
    require(report["source_commit"] == scope["product_commit"]
            and report["inputs_sha256"] == scope["inputs_sha256"]
            and type(report["exit_code"]) is int and report["exit_code"] == 2
            and report["status"] == "incomplete" and report["full_acceptance"] is False
            and report["decision_inventory_complete"] is True
            and set(report["gate_decisions"]) == {f"G{i:02d}" for i in range(1, 17)},
            "projection report source, inputs, inventory or nonpassing result differs")
    expected = {f"G{i:02d}": "verified" for i in range(1, 8)}
    expected.update({gate: "verified" for gate in ("G09", "G11", "G12", "G13")})
    expected.update(G08="failed_requirement", G10="incomplete", G15="unavailable_inputs",
                    G16="blocked", G14=scope["expected_G14_classification"])
    require(report["engine_sha256"] == scope["engine_sha256"]
            and report["network_sha256"] == scope["network_sha256"],
            "projection report actor differs from the separately pinned admission")
    counts = {}
    for gate, classification in expected.items():
        decision = report["gate_decisions"][gate]
        require(decision["gate"] == gate and decision["source_commit"] == scope["product_commit"]
                and decision["engine_sha256"] == report["engine_sha256"]
                and decision["network_sha256"] == report["network_sha256"]
                and decision["classification"] == classification
                and decision["requirement_satisfied"] is (classification == "verified"),
                "projection lost a closed gate, erased a failure or changed source/actor admission")
        counts[classification] = counts.get(classification, 0) + 1
    require(report["decision_counts"] == counts
            and report["original_compiler_runtime_closure"] is False,
            "projection category census or original compiler/runtime limitation differs")
    admission = report["entry_admission"]
    require(admission["scope_sha256"] == scope_sha
            and admission["parent_token_consumed"] is True
            and admission["inherited_host_lease"] is True
            and type(admission["read_only_git_calls"]) is int
            and admission["read_only_git_calls"] == 3,
            "actual entry bootstrap or full source inspection is missing")
    lease.check()
    require(quota.read().get("failure") is None, "projection stage latched a storage failure")
    return {"report": report, "stage": receipt,
            "entry_process": {"pid": child[0].pid, "exit": child[0].returncode,
                              "owned_group_absent_after_reap": True},
            "entry_starts": 1, "parent_token_sha256": record["token_sha256"],
            "full_acceptance": False, "full_R12_complete": False}
