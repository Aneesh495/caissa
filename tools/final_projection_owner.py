"""Unexecuted finite outer owner for the saved-evidence decision entry.

No authority, admission or fixture is created here. A real human renewal and a
separately pinned fresh scope must already exist. Its own process exit still
requires independent post-exit closure; self-reported completion is insufficient.
"""

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import resource
import shutil
import signal
import stat
import sys
import time


ROOT = Path(__file__).resolve().parents[1]


def run(scope_name, expected_scope_sha256):
    started = time.monotonic()
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    inherited_cpu = resource.getrlimit(resource.RLIMIT_CPU)[1]
    inherited_file = resource.getrlimit(resource.RLIMIT_FSIZE)[1]
    bootstrap_cpu = 90 if inherited_cpu == resource.RLIM_INFINITY else min(90, inherited_cpu)
    bootstrap_file = 8 * 1024**2 if inherited_file == resource.RLIM_INFINITY else min(8 * 1024**2, inherited_file)
    if bootstrap_cpu <= 0 or bootstrap_file < 262144:
        raise ValueError("inherited projection owner resource allowance is insufficient")
    resource.setrlimit(resource.RLIMIT_CPU, (bootstrap_cpu, bootstrap_cpu))
    resource.setrlimit(resource.RLIMIT_FSIZE, (bootstrap_file, bootstrap_file))

    def expired(*_):
        raise TimeoutError("projection owner fixed deadline exhausted")

    signal.signal(signal.SIGALRM, expired)
    signal.setitimer(signal.ITIMER_REAL, 120)
    sys.path.insert(0, str(ROOT))
    from verification.final_projection_entry import admit, private_bytes, relative, require, strict_json

    scope, scope_sha, relative_work = admit(scope_name, expected_scope_sha256)
    work = ROOT / relative_work
    require(type(scope["maximum_owner_starts"]) is int and scope["maximum_owner_starts"] == 1,
            "one fresh projection owner start required")
    seconds, cpu = scope["maximum_owner_seconds"], scope["maximum_owner_cpu_seconds"]
    family_limit = scope["maximum_family_cpu_seconds"]
    require(type(seconds) in {int, float} and math.isfinite(seconds) and 10 < seconds <= 120
            and type(cpu) is int and 0 < cpu <= bootstrap_cpu
            and type(family_limit) is int and cpu <= family_limit <= 150
            and scope["deadline_unix"] - scope["origin_unix"] <= seconds,
            "finite separately admitted owner CPU and wall bounds required")
    resource.setrlimit(resource.RLIMIT_CPU, (cpu, cpu))
    remaining = min(seconds - (time.monotonic() - started), scope["deadline_unix"] - time.time())
    require(remaining > 10, "owner admission has no bounded child and cleanup window")
    signal.setitimer(signal.ITIMER_REAL, remaining)
    os.umask(0o077)
    require(all(stat.S_ISFIFO(os.fstat(fd).st_mode) for fd in (1, 2)),
            "projection owner output requires externally owned bounded pipes")
    require(scope["entry_group_policy"] == "inherit_owner_group" and os.getpgrp() == os.getpid(),
            "projection owner must lead the real launcher's owned process group")
    require({p.name for p in work.iterdir()} == {"SCOPE.json"},
            "fresh projection owner work directory already contains another invocation")
    control, emergency, outside = (scope[k] for k in
                                   ("control_bytes", "emergency_control_bytes", "outside_control_bytes"))
    require(type(control) is int and 16000000 <= control <= 32000000
            and type(emergency) is int and emergency == 8000000
            and type(outside) is int and 4000000 <= outside <= 8000000
            and type(scope["reserve_bytes"]) is int and scope["reserve_bytes"] == 128000000,
            "prospective metadata, emergency, outside-control and reserve bounds differ")
    launcher_control, launcher_outside = scope["launcher_control_bytes"], scope["launcher_outside_control_bytes"]
    require(type(launcher_control) is int and 8000000 <= launcher_control <= 16000000
            and type(launcher_outside) is int and launcher_outside == 4000000,
            "separate fully prepaid launcher peak required")
    inventory_name = relative(scope["external_inventory_path"])
    require(inventory_name.startswith(".agent-local/"), "separately pinned private attribution inventory required")
    inventory_raw = private_bytes(inventory_name, 16384)
    require(hashlib.sha256(inventory_raw).hexdigest() == scope["external_inventory_sha256"],
            "external storage inventory differs from independent admission pin")
    inventory = strict_json(inventory_raw)
    external = scope["external_paths"]
    require(inventory["schema"] == "caissa-external-attribution-inventory-v1"
            and inventory["paths"] == external and isinstance(external, list) and len(external) == 19
            and all(isinstance(p, str) and Path(p).is_absolute() and "\0" not in p for p in external)
            and len(set(external)) == 19,
            "complete separately reviewed nineteen-path attribution inventory required")
    bindings = scope["input_bindings"]
    required = {scope["evidence_root"] + "/" + n for n in
                ("MANIFEST.json", "FULL_INPUTS.json", "SOURCE_INPUTS.json")}
    maximum_input = scope["maximum_input_bytes"]
    require(isinstance(bindings, dict) and required <= set(bindings) and len(bindings) <= 1024
            and type(maximum_input) is int and 0 < maximum_input <= 64 * 1024**2,
            "bounded independently pinned evidence input inventory required")

    from tools.campaign_process import Campaign, atomic
    from tools.final_projection_stage import ProjectionQuota, run_entry
    from tools.host_lease import HostLease
    from tools.parallel_storage_quota import check_admission
    from tools.storage_budget import footprint

    # No source or fixture producer runs here. Stable input descriptors only
    # rehash the separately admitted existing metadata/evidence inventory.
    def input_bytes(name):
        parts = relative(name).split("/")
        directory = os.open(ROOT, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            for part in parts[:-1]:
                child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory)
                os.close(directory)
                directory = child
            descriptor = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
                                 dir_fd=directory)
            with os.fdopen(descriptor, "rb") as stream:
                before = os.fstat(stream.fileno())
                require(stat.S_ISREG(before.st_mode) and before.st_nlink == 1
                        and before.st_size <= 16 * 1024**2, "pinned owner input is linked or excessive")
                raw = stream.read(16 * 1024**2 + 1)
                after = os.fstat(stream.fileno())
            stamp = lambda s: (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns)
            require(len(raw) == before.st_size and stamp(before) == stamp(after),
                    "pinned owner input changed during actual descriptor read")
            return raw
        finally:
            os.close(directory)

    lease = HostLease(ROOT / "runs")
    quota, campaign = None, None
    failure, result = None, None
    quota_created, original_error = False, None
    cleanup_errors = []
    last_storage = [0]
    observation = [None]
    spawns, directories = [], []

    def family_cpu():
        own, children = (resource.getrusage(who) for who in
                         (resource.RUSAGE_SELF, resource.RUSAGE_CHILDREN))
        return own.ru_utime + own.ru_stime + children.ru_utime + children.ru_stime

    try:
        total = 0
        for name, expected in bindings.items():
            raw = input_bytes(name)
            total += len(raw)
            require(total <= maximum_input and hashlib.sha256(raw).hexdigest() == expected,
                    "owner pinned evidence bytes or cumulative input bound differ")
        require(hashlib.sha256(input_bytes(scope["evidence_root"] + "/FULL_INPUTS.json")).hexdigest()
                == scope["inputs_sha256"], "owner full-input declaration differs from external pin")

        def guard(force=False):
            lease.check()
            require(time.time() < scope["deadline_unix"], "projection owner deadline exhausted")
            require(family_cpu() <= family_limit, "projection observed family CPU allowance exhausted")
            state = quota.read() if quota is not None else {"control_used": 0, "failure": None}
            require(state.get("failure") is None, "projection owner storage failure latched")
            if force or time.monotonic() - last_storage[0] >= 10:
                actual = footprint([ROOT, *external])
                mac = shutil.disk_usage(ROOT).used
                check_admission(actual["charged_bytes"], mac, 0,
                                control - state["control_used"] + outside
                                + launcher_control + launcher_outside, 128000000)
                observation[0] = {"charged_bytes": actual["charged_bytes"], "mac_used_bytes": mac,
                                  "external_path_count": len(external), "unix": time.time()}
                last_storage[0] = time.monotonic()

        guard(force=True)
        quota = ProjectionQuota({"output": str(work), "ledger": str(work / "WRITE_USAGE.json"),
                                 "scope_sha256": scope_sha, "data_bytes": 0,
                                 "control_bytes": control, "emergency_control_bytes": emergency,
                                 "deadline_unix": scope["deadline_unix"], "reserve_bytes": 128000000})
        quota.create()
        quota_created = True
        quota.install()
        command = [scope["python_command"], "-B", "-P", str(ROOT / "verification/final_projection_entry.py"),
                   "--scope", scope_name, "--expected-scope-sha256", scope_sha]
        ledger_names = {work / n for n in ("WRITE_USAGE.json", "WRITE_USAGE.json.tmp", "WRITE_USAGE.json.lock")}

        def audit(event, args):
            if event.startswith("socket.") or event in {
                "os.system", "os.posix_spawn", "os.exec", "os.link", "os.symlink", "os.remove",
                "os.rmdir", "os.truncate", "os.chmod", "os.chown", "os.utime"
            }:
                raise ValueError("projection owner prohibits network and unadmitted mutation")
            if event == "subprocess.Popen":
                require(args[1] == command and len(spawns) == 0,
                        "projection owner permits one exact decision-entry command")
                spawns.append(True)
            if event == "os.mkdir":
                target = Path(args[0]).absolute()
                require(target == work / "entry-stage" and target == target.resolve()
                        and not directories, "projection owner directory creation escaped")
                directories.append(target)
            if event == "open":
                name, mode, flags = args
                writing = isinstance(mode, str) and any(x in mode for x in "wax+") or (
                    isinstance(flags, int) and flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND))
                if writing:
                    if type(name) is int:
                        require(stat.S_ISFIFO(os.fstat(name).st_mode), "owner regular descriptor write rejected")
                    elif name != os.devnull:
                        target = Path(name).absolute()
                        require(target == target.resolve(), "owner output traverses a link")
                        if target not in ledger_names:
                            quota.classify(target)

        sys.addaudithook(audit)
        with (work / "OWNER_STARTED.json").open("x") as stream:
            json.dump({"schema": "caissa-final-projection-owner-started-v1",
                       "scope_sha256": scope_sha, "owner_pid": os.getpid(), "owner_start": 1,
                       "unix": time.time()}, stream, separators=(",", ":"))
            stream.flush()
            os.fsync(stream.fileno())
        child_window = min(scope["maximum_entry_seconds"], scope["deadline_unix"] - time.time() - 10)
        require(child_window > 0, "projection owner cleanup reserve leaves no child window")
        campaign = Campaign(work / "entry-stage",
                            {"schema": "caissa-final-projection-owner-campaign-v1",
                             "scope_sha256": scope_sha, "source_commit": scope["product_commit"]},
                            child_window, absolute_deadline=scope["deadline_unix"] - 10,
                            resource_guard=guard)
        result = run_entry(scope_name, scope_sha, campaign=campaign, quota=quota, lease=lease)
        guard()
        require(len(spawns) == 1 and len(directories) == 1, "owner actual entry/directory count differs")
        atomic(work / "OWNER_RESULT.json", {"schema": "caissa-final-projection-owner-result-v1",
               "scope_sha256": scope_sha, "entry": result, "input_bytes_rehashed": total,
               "last_storage_observation": observation[0], "owner_self_report": True,
               "observed_own_and_reaped_child_cpu_seconds": family_cpu(),
               "owner_exit_independently_checked": False, "full_R12_complete": False,
               "full_acceptance": False})
    except BaseException as error:
        original_error = error
        failure = {"type": type(error).__name__, "reason": str(error)}
        if quota is not None and quota.old is not None:
            try:
                atomic(work / "FAILED-owner.json", {"schema": "caissa-final-projection-owner-failure-v1",
                       "scope_sha256": scope_sha, "failure": failure, "entry_starts": len(spawns),
                       "full_acceptance": False})
            except BaseException as closure_error:
                cleanup_errors.append("failure-record: " + type(closure_error).__name__)
        raise
    finally:
        if campaign is not None:
            try:
                campaign.close("failed" if failure else "completed_component_only", failure)
            except BaseException as closure_error:
                cleanup_errors.append("campaign-close: " + type(closure_error).__name__)
        if quota_created:
            try:
                quota.update(lambda state: state.update(closed=True, owner_failure=failure,
                             cleanup_errors=cleanup_errors))
            except BaseException as closure_error:
                cleanup_errors.append("ledger-close: " + type(closure_error).__name__)
        for label, close in (("quota-uninstall", quota.uninstall if quota is not None else lambda: None),
                             ("lease-close", lease.close),
                             ("timer-close", lambda: signal.setitimer(signal.ITIMER_REAL, 0))):
            try:
                close()
            except BaseException as closure_error:
                cleanup_errors.append(label + ": " + type(closure_error).__name__)
        if cleanup_errors:
            if original_error is not None:
                original_error.add_note("projection cleanup also failed: " + ", ".join(cleanup_errors))
            else:
                raise RuntimeError("projection cleanup failed: " + ", ".join(cleanup_errors))
    require(family_cpu() <= family_limit, "projection observed CPU allowance exhausted during closure")
    return {"status": "completed_saved_evidence_component_only", "entry_exit": 2,
            "scope_sha256": scope_sha,
            "owner_result_sha256": hashlib.sha256(private_bytes(relative_work + "OWNER_RESULT.json", 4 * 1024**2)).hexdigest(),
            "owner_ledger_sha256": hashlib.sha256(private_bytes(relative_work + "WRITE_USAGE.json", 262144)).hexdigest(),
            "campaign_sha256": hashlib.sha256(private_bytes(relative_work + "entry-stage/CAMPAIGN.json", 262144)).hexdigest(),
            "owner_started_sha256": hashlib.sha256(private_bytes(relative_work + "OWNER_STARTED.json", 8192)).hexdigest(),
            "entry_admission_sha256": hashlib.sha256(private_bytes(relative_work + "ENTRY_ADMISSION.json", 8192)).hexdigest(),
            "observed_own_and_reaped_child_cpu_seconds": family_cpu(),
            "owner_exit_independently_checked": False,
            "full_R12_complete": False, "full_acceptance": False}


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--scope", required=True)
    parser.add_argument("--expected-scope-sha256", required=True)
    args = parser.parse_args(argv)
    try:
        result = run(args.scope, args.expected_scope_sha256)
    except Exception as error:
        print(json.dumps({"status": "rejected", "error_type": type(error).__name__,
                          "full_acceptance": False}))
        return 1
    print(json.dumps(result, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
