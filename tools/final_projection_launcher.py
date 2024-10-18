"""Unexecuted independent owner transport/closure under fresh external admission.

Creates no authority, scope or fixture. Never invoke while human renewal is
pending. It owns one new owner group, with the entry/Git children inheriting it.
"""

import argparse
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import resource
import selectors
import shutil
import signal
import stat
import subprocess
import sys
import time


ROOT = Path(__file__).resolve().parents[1]


def run(scope_name, expected_scope_sha256):
    started = time.monotonic()
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    inherited = resource.getrlimit(resource.RLIMIT_CPU)[1]
    cpu = 90 if inherited == resource.RLIM_INFINITY else min(90, inherited)
    if cpu <= 0:
        raise ValueError("launcher inherited CPU allowance exhausted")
    resource.setrlimit(resource.RLIMIT_CPU, (cpu, cpu))
    inherited = resource.getrlimit(resource.RLIMIT_FSIZE)[1]
    size = 8 * 1024**2 if inherited == resource.RLIM_INFINITY else min(8 * 1024**2, inherited)
    if size < 1024**2:
        raise ValueError("launcher inherited file allowance insufficient")
    resource.setrlimit(resource.RLIMIT_FSIZE, (size, size))
    def expired(*_):
        raise TimeoutError("launcher fixed hard deadline exhausted")
    signal.signal(signal.SIGALRM, expired)
    signal.setitimer(signal.ITIMER_REAL, 145)
    sys.path.insert(0, str(ROOT))
    from verification.final_projection_entry import admit, private_bytes, relative, require, strict_json
    from tools.campaign_process import atomic, group_signal
    from tools.parallel_storage_quota import Quota, check_admission
    from tools.storage_budget import footprint

    scope, scope_sha, owner_prefix = admit(scope_name, expected_scope_sha256)
    owner_work = ROOT / owner_prefix
    root_name = relative(scope["launcher_work"])
    root = ROOT / root_name
    deadline = scope["launcher_deadline_unix"]
    hard_deadline = scope["launcher_hard_deadline_unix"]
    require(len(root_name.split("/")) == 2 and root_name.startswith("work/")
            and root != owner_work and root == root.resolve() and not root.exists(),
            "fresh separate launcher work directory required")
    require(type(scope["maximum_launcher_starts"]) is int and scope["maximum_launcher_starts"] == 1
            and type(scope["maximum_owner_starts"]) is int and scope["maximum_owner_starts"] == 1
            and type(deadline) in {int, float} and math.isfinite(deadline)
            and type(hard_deadline) in {int, float} and math.isfinite(hard_deadline)
            and scope["deadline_unix"] < deadline < hard_deadline <= scope["parent_deadline_unix"]
            and hard_deadline - deadline >= 5
            and hard_deadline - scope["origin_unix"] <= 150
            and type(scope["maximum_owner_cpu_seconds"]) is int
            and 0 < scope["maximum_owner_cpu_seconds"] <= cpu
            and scope["entry_group_policy"] == "inherit_owner_group",
            "fresh finite launcher/owner bounds and group contract required")
    require(scope["python_command"] == sys.executable,
            "launcher must preserve the pinned virtual environment command")
    family_limit = scope["maximum_launcher_family_cpu_seconds"]
    require(type(scope["maximum_launcher_cpu_seconds"]) is int
            and scope["maximum_launcher_cpu_seconds"] == cpu
            and type(scope["maximum_family_cpu_seconds"]) is int
            and 0 < scope["maximum_family_cpu_seconds"] <= 150
            and type(family_limit) is int and 0 < family_limit <= 240
            and family_limit <= scope["maximum_family_cpu_seconds"] + cpu,
            "separate launcher and observed reaped-family CPU bounds required")
    require(hard_deadline - time.time() > 5, "launcher cleanup window already exhausted")
    signal.setitimer(signal.ITIMER_REAL, hard_deadline - time.time() - 5)
    require(all(stat.S_ISFIFO(os.fstat(fd).st_mode) for fd in (1, 2)),
            "launcher output requires externally owned bounded pipes")
    control, outside = scope["launcher_control_bytes"], scope["launcher_outside_control_bytes"]
    require(type(control) is int and 8000000 <= control <= 16000000
            and type(outside) is int and outside == 4000000,
            "finite launcher control and ledger peak reservation required")
    maximum = scope["maximum_owner_output_bytes"]
    require(type(maximum) is int and 1024 <= maximum <= 1024**2,
            "finite owner stdout/stderr capture bound required")
    inventory_name = relative(scope["external_inventory_path"])
    require(inventory_name.startswith(".agent-local/"), "private attribution namespace required")
    raw_inventory = private_bytes(inventory_name, 16384)
    require(hashlib.sha256(raw_inventory).hexdigest() == scope["external_inventory_sha256"],
            "launcher external attribution inventory differs")
    external = scope["external_paths"]
    inventory = strict_json(raw_inventory)
    require(inventory["schema"] == "caissa-external-attribution-inventory-v1"
            and inventory["paths"] == external and isinstance(external, list) and len(external) == 19
            and all(isinstance(p, str) and Path(p).is_absolute() and "\0" not in p for p in external)
            and len(set(external)) == 19,
            "launcher requires the separately reviewed complete attribution inventory")
    with (ROOT / "runs/TIMED_STRENGTH.lock").open("rb") as probe:
        fcntl.flock(probe, fcntl.LOCK_EX | fcntl.LOCK_NB)
        fcntl.flock(probe, fcntl.LOCK_UN)
    actual = footprint([ROOT, *external])
    check_admission(actual["charged_bytes"], shutil.disk_usage(ROOT).used, 0,
                    scope["control_bytes"] + scope["outside_control_bytes"] + control + outside,
                    128000000)
    os.umask(0o077)
    root.mkdir()

    class LauncherQuota(Quota):
        def classify(self, target, *, replacement=False):
            target = Path(target).absolute()
            require(target == target.resolve() and target.parent == root,
                    "launcher metadata writer escaped")
            require(target.name in {"STARTED.json", "owner.stdout", "owner.stderr",
                                   "CLOSED.json", "CLOSED.json.tmp", "FAILED-launcher.json",
                                   "FAILED-launcher.json.tmp", "FAILED-transport.json",
                                   "FAILED-transport.json.tmp"}, "unknown launcher output")
            if target.name in {"STARTED.json", "owner.stdout", "owner.stderr", "CLOSED.json"}:
                require(not target.exists(), "immutable launcher record already exists")
            return "control", target.name

    quota = LauncherQuota({"output": str(root), "ledger": str(root / "WRITE_USAGE.json"),
                          "scope_sha256": scope_sha, "data_bytes": 0, "control_bytes": control,
                          "emergency_control_bytes": 2000000, "reserve_bytes": 128000000,
                          "deadline_unix": deadline})
    quota.create()
    quota.install()
    command = [scope["python_command"], "-B", "-P", str(ROOT / "tools/final_projection_owner.py"),
               "--scope", scope_name, "--expected-scope-sha256", scope_sha]
    environment = {k: v for k, v in os.environ.items()
                   if k not in {"CAISSA_HOST_LEASE_FD", "CAISSA_FINAL_ENTRY_TOKEN_FD"}}
    process, outcome, failure, original_error = None, None, None, None
    group_gone, cleanup_errors = False, []
    streams, counters, spawns = {}, {}, []
    eof_channels = set()
    selector = selectors.DefaultSelector()

    def audit(event, args):
        if event.startswith("socket.") or event in {
            "os.system", "os.posix_spawn", "os.exec", "os.link", "os.symlink", "os.remove",
            "os.mkdir", "os.rmdir", "os.truncate", "os.chmod", "os.chown", "os.utime"
        }:
            raise ValueError("launcher process/network/directory boundary rejected")
        if event == "subprocess.Popen":
            require(args[1] == command and not spawns, "one exact owner launch required")
            spawns.append(True)

    sys.addaudithook(audit)
    try:
        with (root / "STARTED.json").open("x") as stream:
            json.dump({"scope_sha256": scope_sha, "launcher_pid": os.getpid(), "owner_starts": 1}, stream)
        for channel in ("stdout", "stderr"):
            streams[channel] = (root / ("owner." + channel)).open("xb")
            counters[channel] = {"bytes": 0, "retained": 0, "discarded": 0, "hash": hashlib.sha256()}
        process = subprocess.Popen(command, cwd=ROOT, stdin=subprocess.DEVNULL,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, bufsize=0,
                                   start_new_session=True, env=environment)
        for channel in ("stdout", "stderr"):
            pipe = getattr(process, channel)
            os.set_blocking(pipe.fileno(), False)
            selector.register(pipe, selectors.EVENT_READ, channel)
        stopping = None
        owner_exit_observed = None
        while process.poll() is None or selector.get_map():
            now = time.monotonic()
            if process.poll() is not None and owner_exit_observed is None:
                owner_exit_observed = time.time()
            if stopping is None and time.time() >= scope["deadline_unix"] and owner_exit_observed is None:
                failure = "owner fixed deadline exhausted"
                group_signal(process.pid, signal.SIGTERM)
                stopping = now
            if stopping is not None and now - stopping >= 2:
                group_signal(process.pid, signal.SIGKILL)
            for key, _ in selector.select(0.1):
                try:
                    block = os.read(key.fd, 65536)
                except BlockingIOError:
                    continue
                if not block:
                    eof_channels.add(key.data)
                    selector.unregister(key.fileobj)
                    continue
                counter = counters[key.data]
                counter["hash"].update(block)
                counter["bytes"] += len(block)
                keep = min(len(block), max(0, maximum - counter["retained"]))
                streams[key.data].write(block[:keep])
                counter["retained"] += keep
                counter["discarded"] += len(block) - keep
                if counter["discarded"] and stopping is None:
                    failure = "owner output bound exhausted"
                    group_signal(process.pid, signal.SIGTERM)
                    stopping = now
            if time.time() >= deadline or stopping is not None and now - stopping > 5:
                raise TimeoutError("launcher fixed closure deadline exhausted")
        owner_exit = process.wait(timeout=2)
        own_cpu, child_cpu = (resource.getrusage(who) for who in
                              (resource.RUSAGE_SELF, resource.RUSAGE_CHILDREN))
        observed_cpu = own_cpu.ru_utime + own_cpu.ru_stime + child_cpu.ru_utime + child_cpu.ru_stime
        require(observed_cpu <= family_limit, "observed launcher/reaped-family CPU bound exhausted")
        for stream in streams.values():
            stream.flush()
            os.fsync(stream.fileno())
            stream.close()
        owner_exit_observed = owner_exit_observed or time.time()
        require(owner_exit == 0 and owner_exit_observed <= scope["deadline_unix"]
                and failure is None and counters["stderr"]["bytes"] == 0
                and all(c["discarded"] == 0 for c in counters.values()),
                "actual owner exit, stderr or output boundary failed")
        try:
            os.killpg(process.pid, 0)
        except ProcessLookupError:
            group_gone = True
        else:
            raise ValueError("owned owner/entry/Git group remains after reaping")
        stdout_raw = private_bytes(root_name + "/owner.stdout", maximum)
        stderr_stat = (root / "owner.stderr").lstat()
        require(hashlib.sha256(stdout_raw).hexdigest() == counters["stdout"]["hash"].hexdigest()
                and len(stdout_raw) == counters["stdout"]["bytes"]
                and stat.S_ISREG(stderr_stat.st_mode) and stat.S_IMODE(stderr_stat.st_mode) == 0o600
                and stderr_stat.st_nlink == 1 and stderr_stat.st_size == 0,
                "retained owner transport bytes or private modes changed")
        summary = strict_json(stdout_raw)
        result_raw = private_bytes(owner_prefix + "OWNER_RESULT.json", 4 * 1024**2)
        result = strict_json(result_raw)
        ledger_raw = private_bytes(owner_prefix + "WRITE_USAGE.json", 262144)
        ledger = strict_json(ledger_raw)
        campaign_raw = private_bytes(owner_prefix + "entry-stage/CAMPAIGN.json", 262144)
        campaign = strict_json(campaign_raw)
        started_raw = private_bytes(owner_prefix + "OWNER_STARTED.json", 8192)
        admission_raw = private_bytes(owner_prefix + "ENTRY_ADMISSION.json", 8192)
        started_owner = strict_json(started_raw)
        require(summary["status"] == "completed_saved_evidence_component_only"
                and summary["entry_exit"] == 2 and summary["owner_exit_independently_checked"] is False
                and summary["scope_sha256"] == scope_sha
                and summary["owner_result_sha256"] == hashlib.sha256(result_raw).hexdigest()
                and summary["owner_ledger_sha256"] == hashlib.sha256(ledger_raw).hexdigest()
                and summary["campaign_sha256"] == hashlib.sha256(campaign_raw).hexdigest()
                and summary["owner_started_sha256"] == hashlib.sha256(started_raw).hexdigest()
                and summary["entry_admission_sha256"] == hashlib.sha256(admission_raw).hexdigest()
                and started_owner["owner_pid"] == process.pid and started_owner["scope_sha256"] == scope_sha
                and started_owner["owner_start"] == 1
                and result["scope_sha256"] == scope_sha and result["owner_self_report"] is True
                and result["owner_exit_independently_checked"] is False
                and ledger["scope_sha256"] == scope_sha and ledger["closed"] is True
                and ledger.get("failure") is None and ledger.get("owner_failure") is None
                and ledger["cleanup_errors"] == []
                and campaign["status"] == "completed_component_only" and campaign["stages_started"] == 1
                and campaign["full_acceptance"] is False,
                "owner self-report, actual identity, campaign or closed ledger differs")
        entry = result["entry"]
        require(all(value[flag] is False for value in (summary, result, entry)
                    for flag in ("full_R12_complete", "full_acceptance")),
                "owner closure promoted a component to project acceptance")
        stage_raw = private_bytes(owner_prefix + "entry-stage/full-entry.json", 262144)
        stage = strict_json(stage_raw)
        log_raw = private_bytes(owner_prefix + "entry-stage/full-entry.log", 2 * 1024**2)
        canonical = lambda value: json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
        require(stage["exit"] == 2 and stage["reason"] == "nonzero-exit"
                and not stage["cleanup_warnings"] and stage["discarded_output_bytes"] == 0
                and stage["retained_output_bytes"] == len(log_raw)
                and stage["log_sha256"] == hashlib.sha256(log_raw).hexdigest()
                and canonical(stage) == canonical(entry["stage"])
                and canonical(strict_json(log_raw)) == canonical(entry["report"])
                and entry["entry_process"]["owner_group_id"] == process.pid
                and entry["entry_process"]["inherited_owner_group"] is True
                and entry["entry_process"]["final_group_check_pending"] is True
                and entry["entry_starts"] == 1 and entry["report"]["exit_code"] == 2
                and entry["report"]["full_acceptance"] is False,
                "actual entry stage/log/result or inherited group relationship differs")
        require(hashlib.sha256(private_bytes(scope_name, 1024**2)).hexdigest() == scope_sha,
                "scope changed across the actual owner invocation")
        for name, expected in scope["source_bindings"].items():
            target = ROOT / relative(name)
            require(target == target.resolve() and target.stat().st_size <= 4 * 1024**2
                    and hashlib.sha256(target.read_bytes()).hexdigest() == expected,
                    "pinned source changed across owner invocation")
        with (ROOT / "runs/TIMED_STRENGTH.lock").open("rb") as probe:
            fcntl.flock(probe, fcntl.LOCK_EX | fcntl.LOCK_NB)
            fcntl.flock(probe, fcntl.LOCK_UN)
        outcome = {"schema": "caissa-final-projection-independent-owner-closure-v1",
                   "status": "passed_owner_closure_component", "scope_sha256": scope_sha,
                   "owner_pid": process.pid, "owner_exit": owner_exit, "entry_exit": 2,
                   "observed_own_and_reaped_child_cpu_seconds": observed_cpu,
                   "owned_group_absent_after_reap": True, "host_lease_free_observed": True,
                   "owner_result_sha256": hashlib.sha256(result_raw).hexdigest(),
                   "owner_ledger_sha256": hashlib.sha256(ledger_raw).hexdigest(),
                   "campaign_sha256": hashlib.sha256(campaign_raw).hexdigest(),
                   "entry_stage_sha256": hashlib.sha256(stage_raw).hexdigest(),
                   "entry_log_sha256": hashlib.sha256(log_raw).hexdigest(),
                   "owner_transport": {k: {**{n: c[n] for n in ("bytes", "retained", "discarded")},
                                            "sha256": c["hash"].hexdigest()} for k, c in counters.items()},
                   "launcher_exit_independently_checked": False,
                   "full_R12_complete": False, "full_acceptance": False}
        atomic(root / "CLOSED.json", outcome)
    except BaseException as error:
        original_error = error
        failure = failure or type(error).__name__
        try:
            atomic(root / "FAILED-launcher.json", {"scope_sha256": scope_sha, "failure": failure,
                   "owner_pid": process.pid if process else None,
                   "observed_owner_exit": process.returncode if process else None, "full_acceptance": False})
        except BaseException as closure_error:
            cleanup_errors.append("failure-record: " + type(closure_error).__name__)
        raise
    finally:
        closers = [("selector-close", selector.close)]
        if process is not None and not group_gone:
            try:
                group_signal(process.pid, signal.SIGTERM)
                try:
                    process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    group_signal(process.pid, signal.SIGKILL)
                    process.wait(timeout=3)
                try:
                    os.killpg(process.pid, 0)
                except ProcessLookupError:
                    group_gone = True
                else:
                    group_signal(process.pid, signal.SIGKILL)
                    raise ValueError("owned group cleanup needs independent rejection/review")
            except BaseException as closure_error:
                cleanup_errors.append("owned-group-close: " + type(closure_error).__name__)
        if process is not None:
            for channel in ("stdout", "stderr"):
                closers.append((channel + "-pipe-close", getattr(process, channel).close))
        for stream in streams.values():
            closers.append(("log-close", stream.close))
        if failure is not None:
            closers.append(("failed-transport", lambda: atomic(root / "FAILED-transport.json", {
                "scope_sha256": scope_sha, "owner_pid": process.pid if process else None,
                "actual_reaped_owner_exit": process.returncode if process else None,
                "owned_group_absent_observed": group_gone,
                "transport_both_streams_fully_drained": eof_channels == {"stdout", "stderr"},
                "observed_streams": {k: {**{n: c[n] for n in ("bytes", "retained", "discarded")},
                                          "observed_sha256": c["hash"].hexdigest()} for k, c in counters.items()},
                "cleanup_errors_so_far": cleanup_errors, "full_acceptance": False})))
        closers.extend([("ledger-close", lambda: quota.update(lambda state: state.update(
                       closed=True, launcher_failure=failure, cleanup_errors=cleanup_errors))),
                        ("quota-uninstall", quota.uninstall),
                        ("timer-close", lambda: signal.setitimer(signal.ITIMER_REAL, 0))])
        for label, close in closers:
            try:
                close()
            except BaseException as closure_error:
                cleanup_errors.append(label + ": " + type(closure_error).__name__)
        if cleanup_errors:
            if original_error is not None:
                original_error.add_note("launcher cleanup also failed: " + ", ".join(cleanup_errors))
            else:
                raise RuntimeError("launcher cleanup failed: " + ", ".join(cleanup_errors))
    own_cpu, child_cpu = (resource.getrusage(who) for who in
                          (resource.RUSAGE_SELF, resource.RUSAGE_CHILDREN))
    final_cpu = own_cpu.ru_utime + own_cpu.ru_stime + child_cpu.ru_utime + child_cpu.ru_stime
    require(group_gone and final_cpu <= family_limit and time.time() < hard_deadline
            and time.monotonic() - started <= 150,
            "launcher closure exceeded its fixed finite window")
    return {"status": outcome["status"], "owner_exit": 0, "entry_exit": 2,
            "observed_own_and_reaped_child_cpu_seconds": final_cpu,
            "launcher_exit_independently_checked": False,
            "full_R12_complete": False, "full_acceptance": False}


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--scope", required=True)
    parser.add_argument("--expected-scope-sha256", required=True)
    args = parser.parse_args(argv)
    try:
        result = run(args.scope, args.expected_scope_sha256)
    except Exception as error:
        print(json.dumps({"status": "rejected", "error_type": type(error).__name__, "full_acceptance": False}))
        return 1
    print(json.dumps(result, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
