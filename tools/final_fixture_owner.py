"""Unexecuted finite seed/control owner; requires genuine external admission.

No renewal, scope or consumer is admitted here. An independent executor must
review actual human provenance, enforce cumulative family limits, own output
pipes and verify the real owner exit and final process-group absence.
"""

import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import resource
import signal
import stat
import sys
import time


ROOT = Path(__file__).resolve().parents[1]


def require(value, reason):
    if not value:
        raise ValueError(reason)


def bootstrap_read(name, maximum):
    require(isinstance(name, str) and not name.startswith("/") and "\\" not in name
            and 0 < len(name.encode()) <= 4096
            and all(p not in {"", ".", ".."} for p in name.split("/"))
            and all(32 <= ord(c) != 127 for c in name), "invalid owner bootstrap path")
    parts = name.split("/")
    directory = os.open(ROOT, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for part in parts[:-1]:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory)
            os.close(directory)
            directory = child
        descriptor = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
        with os.fdopen(descriptor, "rb") as stream:
            before = os.fstat(stream.fileno())
            require(stat.S_ISREG(before.st_mode) and before.st_nlink == 1
                    and 0 <= before.st_size <= maximum, "owner bootstrap input is linked or excessive")
            raw = stream.read(maximum + 1)
            after = os.fstat(stream.fileno())
        stamp = lambda x: (x.st_dev, x.st_ino, x.st_size, x.st_mtime_ns, x.st_ctime_ns)
        require(len(raw) == before.st_size and stamp(before) == stamp(after),
                "owner bootstrap descriptor changed during read")
        return raw, stat.S_IMODE(before.st_mode)
    finally:
        os.close(directory)


def run(scope_name, expected_scope_sha256, verified_human_message_sha256):
    started = time.monotonic()
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    hard_cpu, hard_file = (resource.getrlimit(k)[1] for k in (resource.RLIMIT_CPU, resource.RLIMIT_FSIZE))
    cpu = 90 if hard_cpu == resource.RLIM_INFINITY else min(90, hard_cpu)
    maximum_file = 8 * 1024**2 if hard_file == resource.RLIM_INFINITY else min(8 * 1024**2, hard_file)
    require(cpu > 0 and maximum_file >= 262144, "inherited fixture owner limits are insufficient")
    resource.setrlimit(resource.RLIMIT_CPU, (cpu, cpu))
    resource.setrlimit(resource.RLIMIT_FSIZE, (maximum_file, maximum_file))

    def expired(*_):
        raise TimeoutError("fixture owner fixed wall deadline exhausted")

    signal.signal(signal.SIGALRM, expired)
    signal.setitimer(signal.ITIMER_REAL, 150)
    require(sys.dont_write_bytecode and sys.flags.safe_path and Path.cwd().resolve() == ROOT
            and os.getpgrp() == os.getpid()
            and all(stat.S_ISFIFO(os.fstat(fd).st_mode) for fd in (1, 2)),
            "fixture owner needs safe startup, an externally owned group and output pipes")
    raw, mode = bootstrap_read(scope_name, 1024**2)
    require(mode == 0o600 and hashlib.sha256(raw).hexdigest() == expected_scope_sha256,
            "fixture owner scope differs from its independent private pin")
    preliminary = json.loads(raw)
    descriptor = os.open(ROOT / "runs/TIMED_STRENGTH.lock", os.O_RDONLY | os.O_NOFOLLOW)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        fcntl.flock(descriptor, fcntl.LOCK_UN)
    finally:
        os.close(descriptor)
    bootstrap = {"tools/final_fixture_owner.py", "tools/final_fixture_git.py",
                 "tools/final_fixture_admission.py", "tools/final_fixture_quota.py",
                 "tools/final_projection_bundle_controls.py", "tools/parallel_storage_quota.py",
                 "tools/host_lease.py", "tools/storage_budget.py"}
    for name in bootstrap:
        body, _ = bootstrap_read(name, 4 * 1024**2)
        require(hashlib.sha256(body).hexdigest() == preliminary["source_bindings"][name],
                "fixture owner bootstrap source changed")
    remaining = min(150 - (time.monotonic() - started), preliminary["deadline_unix"] - time.time())
    require(remaining > 10, "fixture owner admission leaves no helper and cleanup window")
    signal.setitimer(signal.ITIMER_REAL, remaining)

    def reject_cached_project_code(event, args):
        if event == "open" and isinstance(args[0], (str, bytes, os.PathLike)):
            path = Path(os.fsdecode(args[0])).absolute()
            if path.is_relative_to(ROOT) and path.suffix == ".pyc":
                raise FileNotFoundError("fixture bootstrap requires pinned source bytes")

    sys.addaudithook(reject_cached_project_code)
    sys.path.insert(0, str(ROOT))
    from tools.final_fixture_admission import (
        EXPIRED_PARENT, REQUIRED_SOURCES, bind_payload_inputs, digest, document, owner_limits,
        relative, runtime_digest, stable,
    )

    scope = document(raw)
    work_name = relative(scope["work"])
    work = ROOT / work_name
    require(scope_name == work_name + "/SCOPE.json" and work == work.resolve(),
            "fixture owner namespace differs")
    names = []
    with os.scandir(work) as children:
        for child in children:
            require(not names, "fixture owner namespace is already consumed")
            names.append(child.name)
    require(names == ["SCOPE.json"], "fixture owner needs the sole separately admitted scope")
    request_raw = stable(scope["request_path"], 1024**2, private=True)
    require(hashlib.sha256(request_raw).hexdigest() == digest(scope["request_sha256"]),
            "fixture owner's original independently admitted request changed")
    request = document(request_raw)
    owner_limits(request)
    require(scope["schema"] == "caissa-final-fixture-owner-scope-v1"
            and request["schema"] == "caissa-final-fixture-admission-request-v1"
            and request["root"] == str(ROOT)
            and request["python_command"] == sys.executable and request["python_prefix"] == sys.prefix
            and request["interpreter"] == str(Path(sys.executable).resolve())
            and request["maximum_owner_cpu_seconds"] <= cpu,
            "fixture owner source, startup or resource admission differs")
    cpu = request["maximum_owner_cpu_seconds"]
    resource.setrlimit(resource.RLIMIT_CPU, (cpu, cpu))
    human_raw = stable(scope["authority_path"], 16384, private=True)
    human = document(human_raw)
    require(hashlib.sha256(human_raw).hexdigest() == digest(scope["authority_sha256"])
            and human["schema"] == "caissa-direct-human-metadata-renewal-v1"
            and human["scope"] == "saved-evidence-metadata-only"
            and isinstance(human["literal_user_message"], str) and human["literal_user_message"].strip()
            and hashlib.sha256(human["literal_user_message"].encode()).hexdigest()
            == digest(verified_human_message_sha256) == scope["verified_human_message_sha256"]
            and EXPIRED_PARENT < human["received_unix"] <= request["origin_unix"] <= time.time()
            < request["deadline_unix"] <= human["deadline_unix"]
            and 0 < human["deadline_unix"] - human["received_unix"] <= 7200
            and scope["parent_deadline_unix"] == human["deadline_unix"],
            "fixture owner lacks the same independently reviewed real human continuation")
    require(scope["payload"]["parent_deadline_unix"] == human["deadline_unix"],
            "fixture helper human parent differs from its actual owner")
    require(REQUIRED_SOURCES <= set(scope["source_bindings"])
            and len(scope["source_bindings"]) <= 512 and len(scope["input_bindings"]) <= 1024,
            "fixture owner source or input catalog is incomplete or excessive")
    pin_bytes = 0

    def pins():
        nonlocal pin_bytes
        sizes = {}
        for bindings, maximum, total_max in ((scope["source_bindings"], 4 * 1024**2, 32 * 1024**2),
                                            (scope["input_bindings"], 16 * 1024**2, 64 * 1024**2)):
            total = 0
            for name, expected in bindings.items():
                body = stable(name, maximum)
                total += len(body)
                pin_bytes += len(body)
                require(total <= total_max and pin_bytes <= scope["maximum_owner_pin_read_bytes"]
                        and hashlib.sha256(body).hexdigest() == digest(expected),
                        "fixture owner pinned bytes or finite read ceiling differ")
                if bindings is scope["input_bindings"]:
                    sizes[name] = len(body)
        bind_payload_inputs(request, sizes)
        head_raw = stable(".git/HEAD", 8192)
        if head_raw.startswith(b"ref: "):
            reference = relative(head_raw.decode().strip().removeprefix("ref: "))
            require(reference.startswith("refs/heads/")
                    and {".git/HEAD", ".git/" + reference} <= set(scope["source_bindings"])
                    and stable(".git/" + reference, 8192).strip().decode() == scope["product_commit"],
                    "fixture owner current branch is not the independently pinned commit")
        else:
            require(".git/HEAD" in scope["source_bindings"]
                    and head_raw.strip().decode() == scope["product_commit"],
                    "fixture owner detached HEAD differs")
        require(runtime_digest(Path(sys.executable).resolve(), 32 * 1024**2)
                == scope["interpreter_sha256"]
                and runtime_digest(Path(scope["git_executable"]), 64 * 1024**2) == scope["git_sha256"],
                "fixture owner runtime executable identity changed")

    # Every project source is rehashed before importing the remaining owner/helper
    # graph. Import reads of project bytecode are denied, including warm caches.
    inventory_raw = stable(scope["external_inventory_path"], 16384, private=True)
    inventory = document(inventory_raw)
    require(hashlib.sha256(inventory_raw).hexdigest() == scope["external_inventory_sha256"]
            and inventory["schema"] == "caissa-external-attribution-inventory-v1"
            and inventory["paths"] == scope["external_paths"]
            and len(scope["external_paths"]) == len(set(scope["external_paths"])) == 19
            and all(Path(p).is_absolute() for p in scope["external_paths"]),
            "fixture owner external attribution differs from independent review")
    quota, lease, git = None, None, None
    storage_admitted, lease_opens, quota_created = False, 0, False
    failure, original_error, cleanup_errors = None, None, []
    directories, last_storage, observation = set(), 0, None
    ledger_paths = {work / ("WRITE_USAGE.json" + suffix) for suffix in ("", ".tmp", ".lock")}

    def audit(event, args):
        nonlocal lease_opens
        if event == "import":
            name = args[0].replace(".", "/")
            for candidate in (name + ".py", name + "/__init__.py"):
                if (ROOT / candidate).is_file():
                    require(candidate in scope["source_bindings"], "unpinned project source import rejected")
        if event == "subprocess.Popen":
            require(git is not None, "fixture child started outside the owned source reader")
            git.admit_spawn(args)
        if event.startswith("socket.") or event in {
            "os.system", "os.posix_spawn", "os.exec", "os.fork", "os.forkpty", "os.link", "os.symlink",
            "os.remove", "os.rmdir", "os.truncate", "os.chown", "os.utime", "os.chdir"
        }:
            raise ValueError("fixture owner prohibits network and unrelated mutation")
        if event == "os.chmod":
            require(Path(args[0]).absolute() == work / "WRITE_USAGE.json" and args[1] == 0o600
                    and storage_admitted, "fixture owner permission mutation rejected")
        if event == "os.rename":
            require(Path(args[0]).absolute() == work / "WRITE_USAGE.json.tmp"
                    and Path(args[1]).absolute() == work / "WRITE_USAGE.json" and storage_admitted,
                    "fixture owner replacement rejected outside ledger internals")
        if event == "os.mkdir":
            target = Path(args[0]).absolute()
            require(quota is not None and target == target.resolve()
                    and (target == work or str(target.relative_to(work)) in quota.directories)
                    and storage_admitted, "fixture owner directory escaped its exact inventory")
            if not target.exists():
                require(target not in directories, "fixture directory creation repeated")
                directories.add(target)
        if event == "open":
            name, mode, flags = args
            writing = isinstance(mode, str) and any(c in mode for c in "wax+") or (
                isinstance(flags, int) and flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND))
            if not writing and isinstance(name, (str, bytes, os.PathLike)):
                path = Path(os.fsdecode(name)).absolute()
                if path.is_relative_to(ROOT) and path.suffix == ".pyc":
                    raise FileNotFoundError("fixture owner requires pinned project source, not cached bytecode")
            if writing:
                if type(name) is int:
                    require(stat.S_ISFIFO(os.fstat(name).st_mode), "fixture regular descriptor write rejected")
                elif name != os.devnull:
                    target = Path(name).absolute()
                    require(target == target.resolve(), "fixture writer traverses a link")
                    if target == ROOT / "runs/TIMED_STRENGTH.lock":
                        require(lease is None and lease_opens == 0, "fixture lease writer reopened")
                        lease_opens += 1
                    elif target in ledger_paths:
                        require(storage_admitted and quota is not None, "unadmitted fixture ledger write")
                    else:
                        require(storage_admitted and quota is not None, "unadmitted fixture payload write")
                        quota.classify(target)

    sys.addaudithook(audit)
    from tools.final_fixture_git import FixtureGit
    from tools.final_fixture_quota import FixtureQuota, reservation_floor
    from tools.host_lease import HostLease
    from tools.parallel_storage_quota import check_admission
    from tools.storage_budget import footprint
    import shutil

    floor = reservation_floor(request)
    expected_scope = {**request, "schema": "caissa-final-fixture-owner-scope-v1", "status": "admitted",
                      "request_path": scope["request_path"], "request_sha256": scope["request_sha256"],
                      "verified_human_message_sha256": verified_human_message_sha256,
                      "parent_deadline_unix": human["deadline_unix"], "constructor_invocations": 1,
                      "writer_reservation_floor": floor, "full_R12_complete": False, "full_acceptance": False}
    require(scope == expected_scope, "fixture scope differs from exact constructor and request relationship")
    require(shutil.which("git") is not None
            and str(Path(shutil.which("git")).resolve()) == scope["git_executable"],
            "fixture Git resolution differs from the pinned executable")

    def family_cpu():
        values = [resource.getrusage(k) for k in (resource.RUSAGE_SELF, resource.RUSAGE_CHILDREN)]
        return sum(v.ru_utime + v.ru_stime for v in values)

    def guard(force=False):
        nonlocal last_storage, observation
        lease.check()
        require(time.time() < scope["deadline_unix"] - 10
                and family_cpu() <= scope["maximum_family_cpu_seconds"],
                "fixture helper fixed time or observed family CPU exhausted")
        state = quota.read() if quota_created else {"data_used": 0, "control_used": 0}
        require(not state.get("closed", False) and state.get("failure") is None,
                "fixture owner storage ledger is closed or failed")
        if force or time.monotonic() - last_storage >= 10:
            actual = footprint([ROOT, *scope["external_paths"]])
            mac = shutil.disk_usage(ROOT).used
            check_admission(actual["charged_bytes"], mac,
                            scope["data_bytes"] - state["data_used"],
                            scope["control_bytes"] - state["control_used"] + scope["outside_control_bytes"],
                            128000000)
            observation = {"charged_bytes": actual["charged_bytes"], "mac_used_bytes": mac,
                           "external_path_count": 19, "unix": time.time()}
            last_storage = time.monotonic()

    def write(name, value):
        body = (json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n").encode()
        require(len(body) <= scope["writer_file_bounds"][name], "fixture owner metadata cap exhausted")
        with (work / name).open("xb") as stream:
            stream.write(body)
            stream.flush()
            os.fsync(stream.fileno())
        return hashlib.sha256(body).hexdigest()

    try:
        require(resource.getrusage(resource.RUSAGE_CHILDREN).ru_utime
                + resource.getrusage(resource.RUSAGE_CHILDREN).ru_stime == 0,
                "fixture owner inherited an already consumed child CPU counter")
        require("CAISSA_HOST_LEASE_FD" not in os.environ, "fixture owner must acquire its own real lease")
        lease = HostLease(ROOT / "runs")
        os.environ["CAISSA_HOST_LEASE_FD"] = str(lease.stream.fileno())
        pins()
        quota = FixtureQuota(scope, expected_scope_sha256)
        guard(force=True)
        require(max(scope["writer_file_bounds"].values()) <= maximum_file,
                "fixture file caps exceed inherited owner file limit")
        storage_admitted = True
        quota.create()
        quota_created = True
        quota.install()
        write("OWNER_STARTED.json", {"schema": "caissa-final-fixture-owner-started-v1",
              "owner_pid": os.getpid(), "owner_group": os.getpgrp(), "owner_start": 1,
              "scope_sha256": expected_scope_sha256, "operation": scope["operation"], "unix": time.time()})
        (work / "output").mkdir()
        git = FixtureGit(ROOT, scope, guard)
        git.install()
        payload = scope["payload"]
        if scope["operation"] == "build-seed":
            from tools.final_projection_seed import build_seed
            result = build_seed(payload, expected_scope_sha256, quota, lease)
            require(result["status"] == "built_unaccepted_projection_seed_candidate"
                    and result["projection_calls"] == 0 and result["consumer_admitted"] is False,
                    "fixture seed result promoted itself or omitted its real operation")
        else:
            from tools.final_projection_bundle_controls import run_controls
            result = run_controls(ROOT / payload["seed"], ROOT / payload["fixture"],
                                  ROOT / payload["case_archive"], payload, expected_scope_sha256, quota, lease)
            require(result["status"] == "passed_new_bundle_controls_component"
                    and result["actual_projection_calls"] == len(result["controls"]) == 13
                    and result["seed_bytes_preserved"] is True,
                    "fixture control result omitted the real baseline, cases or seed preservation")
        require(result["full_R12_complete"] is False and result["full_acceptance"] is False
                and len(git.rows) == scope["maximum_source_git_commands"],
                "fixture helper result or exact source command count differs")
        pins()
        guard()
        helper_sha = write("HELPER_RESULT.json", result)
        state = quota.read()
        require(state.get("fixture_mutable_opens", {}) == quota.mutable,
                "fixture actual mutable writer counts differ from exact planned operations")
        write("OWNER_RESULT.json", {"schema": "caissa-final-fixture-owner-result-v1",
              "scope_sha256": expected_scope_sha256, "operation": scope["operation"],
              "helper_result_sha256": helper_sha, "git_commands": git.rows,
              "read_only_historical_lock_opens": quota.read_only_lock_opens,
              "explicit_source_input_pin_bytes_read": pin_bytes, "created_directory_count": len(directories),
              "last_storage_observation": observation, "observed_self_and_reaped_child_cpu_seconds": family_cpu(),
              "owner_exit_independently_checked": False, "final_group_check_pending": True,
              "full_R12_complete": False, "full_acceptance": False})
        require(quota.consumed == (quota.immutable | set(quota.mutable)) - {"FAILED-owner.json"},
                "fixture actual output inventory is incomplete")
    except BaseException as error:
        original_error = error
        failure = {"type": type(error).__name__, "reason": str(error)[:2048]}
        if quota is not None and quota.old is not None:
            try:
                write("FAILED-owner.json", {"schema": "caissa-final-fixture-owner-failure-v1",
                      "scope_sha256": expected_scope_sha256, "failure": failure,
                      "git_commands": git.rows if git is not None else [],
                      "read_only_historical_lock_opens": quota.read_only_lock_opens,
                      "full_acceptance": False})
            except BaseException as cleanup_error:
                cleanup_errors.append("failure-record: " + type(cleanup_error).__name__)
        raise
    finally:
        if lease is not None:
            os.environ.pop("CAISSA_HOST_LEASE_FD", None)
        if git is not None:
            git.uninstall()
        if quota_created:
            try:
                quota.update(lambda value: value.update(closed=True, owner_failure=failure,
                             cleanup_errors=cleanup_errors))
            except BaseException as cleanup_error:
                cleanup_errors.append("ledger-close: " + type(cleanup_error).__name__)
        for label, close in (("quota", quota.uninstall if quota is not None else lambda: None),
                             ("lease", lease.close if lease is not None else lambda: None)):
            try:
                close()
            except BaseException as cleanup_error:
                cleanup_errors.append(label + ": " + type(cleanup_error).__name__)
        if original_error is not None or cleanup_errors:
            signal.setitimer(signal.ITIMER_REAL, 0)
        if cleanup_errors:
            if original_error is not None:
                original_error.add_note("fixture owner cleanup also failed: " + ", ".join(cleanup_errors))
            else:
                raise RuntimeError("fixture owner cleanup failed: " + ", ".join(cleanup_errors))
    require(time.time() < scope["deadline_unix"] and time.monotonic() - started <= 150
            and family_cpu() <= scope["maximum_family_cpu_seconds"], "fixture closure exhausted fixed limits")
    identities = {name: hashlib.sha256(stable(work_name + "/" + name, 1024**2, private=True)).hexdigest()
                  for name in ("OWNER_STARTED.json", "HELPER_RESULT.json", "OWNER_RESULT.json", "WRITE_USAGE.json")}
    require(time.time() < scope["deadline_unix"] and time.monotonic() - started <= 150
            and family_cpu() <= scope["maximum_family_cpu_seconds"], "fixture final readback exceeded fixed limits")
    signal.setitimer(signal.ITIMER_REAL, 0)
    return {"status": "completed_fixture_component_self_report", "scope_sha256": expected_scope_sha256,
            "operation": scope["operation"], "post_cleanup_sha256": identities,
            "owner_exit_independently_checked": False, "final_group_check_pending": True,
            "full_R12_complete": False, "full_acceptance": False}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--scope", required=True)
    parser.add_argument("--expected-scope-sha256", required=True)
    parser.add_argument("--verified-human-message-sha256", required=True)
    args = parser.parse_args()
    try:
        result = run(args.scope, args.expected_scope_sha256, args.verified_human_message_sha256)
        raw = json.dumps(result, allow_nan=False)
        require(len(raw.encode()) <= 4096, "fixture owner result output bound exhausted")
    except Exception as error:
        print(json.dumps({"status": "rejected", "error_type": type(error).__name__, "full_acceptance": False}))
        return 1
    print(raw)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
