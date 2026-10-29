"""Unexecuted designated decision entry, requiring fresh external admission.

No scope, authority record, token or owner is created here. The admitted parent
must enforce its once-only owner/stage and shared quotas before launching this
read-only child. This entry cannot renew an expired continuation.
"""

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import re
import resource
import shutil
import signal
import stat
import struct
import subprocess
import sys
import time


ROOT = Path(__file__).resolve().parents[1]
TOKEN_ENV = "CAISSA_FINAL_ENTRY_TOKEN_FD"
LAST_EXPIRED_PARENT = 1793283600.005172
REQUIRED_SOURCES = {
    "verification/final_projection_entry.py", "verification/final_projection.py",
    "verification/final_audit_trust.py", "verification/final_audit_bundle.py",
    "verification/final_semantic_bundle.py", "verification/final_semantic_join.py",
    "verification/final_gate_decisions.py", "verification/final_core_bundle.py",
    "verification/final_evidence_bundle.py", "verification/full_bundle.py",
    "verification/bundle.py", "verification/source.py", "tools/host_lease.py",
    "tools/heuristic_study.py", "tools/final_projection_stage.py",
    "tools/campaign_process.py", "tools/parallel_storage_quota.py", "tools/storage_budget.py",
    "config/final-gate-decisions-v1.json",
}


def require(value, reason):
    if not value:
        raise ValueError(reason)


def strict_json(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            require(key not in result, "duplicate admission JSON key")
            result[key] = value
        return result

    def nonfinite(_):
        raise ValueError("nonfinite admission JSON number")

    def floating(value):
        result = float(value)
        require(math.isfinite(result), "nonfinite admission JSON number")
        return result

    return json.loads(raw, object_pairs_hook=pairs, parse_constant=nonfinite, parse_float=floating)


def relative(name):
    require(isinstance(name, str) and 0 < len(name.encode()) <= 4096
            and not name.startswith("/") and "\\" not in name
            and all(x not in {"", ".", ".."} for x in name.split("/"))
            and all(32 <= ord(c) != 127 for c in name), "noncanonical entry input path")
    return name


def digest(value):
    require(isinstance(value, str) and re.fullmatch("[0-9a-f]{64}", value),
            "malformed external admission digest")
    return value


def private_bytes(name, maximum):
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
            require(stat.S_ISREG(before.st_mode) and stat.S_IMODE(before.st_mode) == 0o600
                    and before.st_nlink == 1 and 0 < before.st_size <= maximum,
                    "entry admission input is linked, public, empty or excessive")
            raw = stream.read(maximum + 1)
            after = os.fstat(stream.fileno())
        stamp = lambda x: (x.st_dev, x.st_ino, x.st_size, x.st_mtime_ns, x.st_ctime_ns)
        require(len(raw) == before.st_size and stamp(before) == stamp(after),
                "entry admission input changed during read")
        return raw
    finally:
        os.close(directory)


def finite(value):
    require(type(value) in {int, float} and math.isfinite(value), "invalid entry time bound")
    return value


def admit(scope_name, expected_scope_sha256):
    scope_name = relative(scope_name)
    require(scope_name.startswith("work/") and scope_name.endswith("/SCOPE.json"),
            "designated entry requires a real separately admitted work scope")
    raw = private_bytes(scope_name, 1024**2)
    scope_sha = hashlib.sha256(raw).hexdigest()
    require(scope_sha == digest(expected_scope_sha256), "entry scope differs from external pin")
    scope = strict_json(raw)
    now = time.time()
    require(scope["schema"] == "caissa-final-projection-entry-scope-v1"
            and scope["status"] == "admitted" and scope["root"] == str(ROOT)
            and finite(scope["origin_unix"]) <= now < finite(scope["deadline_unix"])
            <= finite(scope["parent_deadline_unix"])
            and 0 < finite(scope["maximum_entry_seconds"]) <= 60
            and type(scope["maximum_entry_starts"]) is int and scope["maximum_entry_starts"] == 1,
            "fresh finite decision-entry admission required")
    for key in ("native_starts", "browser_starts", "compiler_starts", "training_starts",
                "inference_starts", "game_starts", "new_parallel_starts", "extra_parallel_active_seconds"):
        require(type(scope[key]) is int and scope[key] == 0, "decision entry admits metadata only")
    authority_name = relative(scope["authority_path"])
    require(authority_name.startswith(".agent-local/"), "direct human authority record required")
    authority_raw = private_bytes(authority_name, 16384)
    require(hashlib.sha256(authority_raw).hexdigest() == digest(scope["authority_sha256"]),
            "direct human authority differs from entry admission")
    authority = strict_json(authority_raw)
    require(authority["schema"] == "caissa-direct-human-metadata-renewal-v1"
            and authority["scope"] == "saved-evidence-metadata-only"
            and isinstance(authority["literal_user_message"], str)
            and authority["literal_user_message"].strip()
            and LAST_EXPIRED_PARENT < finite(authority["received_unix"])
            <= scope["origin_unix"] <= now
            < finite(authority["deadline_unix"]) == scope["parent_deadline_unix"]
            and 0 < authority["deadline_unix"] - authority["received_unix"] <= 7200,
            "expired parents or scheduled acknowledgements cannot renew entry authority")
    require(sys.dont_write_bytecode and sys.flags.safe_path and Path.cwd().resolve() == ROOT
            and sys.prefix == scope["python_prefix"]
            and str(Path(sys.executable).resolve()) == scope["interpreter"],
            "entry requires the admitted Python environment and safe startup")
    executable = Path(sys.executable).resolve()
    require(executable.is_file() and executable.stat().st_size <= 32 * 1024**2
            and hashlib.sha256(executable.read_bytes()).hexdigest() == digest(scope["interpreter_sha256"]),
            "entry interpreter identity differs")
    git_name = shutil.which("git")
    require(git_name is not None, "admitted source Git executable is unavailable")
    git = Path(git_name).resolve()
    require(str(git) == scope["git_executable"] and git.is_file()
            and git.stat().st_size <= 64 * 1024**2
            and hashlib.sha256(git.read_bytes()).hexdigest() == digest(scope["git_sha256"]),
            "entry source Git executable identity differs")
    pins = scope["source_bindings"]
    require(isinstance(pins, dict) and REQUIRED_SOURCES <= set(pins) and len(pins) <= 512,
            "entry source graph is incomplete or excessive")
    total = 0
    for name, expected in pins.items():
        target = ROOT / relative(name)
        require(target.resolve() == target and target.is_file() and target.stat().st_size <= 4 * 1024**2,
                "entry pinned source missing, linked or excessive")
        source = target.read_bytes()
        total += len(source)
        require(total <= 32 * 1024**2 and hashlib.sha256(source).hexdigest() == digest(expected),
                "entry pinned source changed or cumulative source bound exceeded")
    require(re.fullmatch("[0-9a-f]{40}", scope["product_commit"]), "invalid admitted source commit")
    digest(scope["inputs_sha256"])
    require(isinstance(scope["entry_nonce"], str)
            and re.fullmatch("[0-9a-f]{64}", scope["entry_nonce"]), "invalid entry admission nonce")
    evidence = relative(scope["evidence_root"])
    require(evidence.startswith(("runs/", "work/")), "entry evidence must stay in project accounting")
    return scope, scope_sha, scope_name.removesuffix("SCOPE.json")


def consume_parent_token(scope, scope_sha, work):
    raw_fd = os.environ.get(TOKEN_ENV, "")
    require(raw_fd.isascii() and raw_fd.isdecimal() and 3 <= int(raw_fd) <= 1048576,
            "single-use inherited parent admission token required")
    descriptor = int(raw_fd)
    require(str(descriptor) != os.environ.get("CAISSA_HOST_LEASE_FD")
            and stat.S_ISFIFO(os.fstat(descriptor).st_mode), "invalid parent token descriptor")
    os.set_blocking(descriptor, False)
    try:
        raw = os.read(descriptor, 4097)
        require(0 < len(raw) <= 4096 and os.read(descriptor, 1) == b"",
                "parent token must be one bounded prewritten closed pipe")
    finally:
        os.close(descriptor)
        os.environ.pop(TOKEN_ENV, None)
    token = strict_json(raw)
    record = strict_json(private_bytes(work + "ENTRY_ADMISSION.json", 8192))
    require(isinstance(token, dict) and isinstance(record, dict)
            and set(token) == {"scope_sha256", "nonce", "owner_pid", "invocation"}
            and set(record) == set(token) | {"schema", "token_sha256"}
            and record["schema"] == "caissa-final-entry-parent-admission-v1"
            and token["scope_sha256"] == record["scope_sha256"] == scope_sha
            and token["nonce"] == record["nonce"] == scope["entry_nonce"]
            and type(token["owner_pid"]) is type(record["owner_pid"]) is int
            and token["owner_pid"] == record["owner_pid"] == os.getppid()
            and type(token["invocation"]) is type(record["invocation"]) is int
            and token["invocation"] == record["invocation"] == 1
            and hashlib.sha256(raw).hexdigest() == record["token_sha256"],
            "entry parent, scope, nonce or invocation token differs")


def install_read_only_guard(scope):
    commands, pipe_opens = [], []
    allowed = [["git", "rev-parse", "HEAD"], ["git", "cat-file", "--batch"],
               ["git", "ls-tree", "-r", "-l", "-z", "--full-tree", scope["product_commit"]]]

    def audit(event, args):
        if event.startswith("socket.") or event in {
            "os.system", "os.posix_spawn", "os.exec", "os.link", "os.symlink", "os.remove",
            "os.rename", "os.mkdir", "os.truncate", "os.chmod", "os.chown", "os.utime"
        }:
            raise ValueError("decision entry prohibits network and mutation")
        if event == "subprocess.Popen":
            require(args[1] in allowed and Path(args[2] or ROOT).resolve() == ROOT and len(commands) < 3,
                    "decision entry permits only exact bounded read-only source Git commands")
            commands.append(args[1])
        if event == "open":
            name, mode, flags = args
            writing = (isinstance(mode, str) and any(c in mode for c in "wax+")) or (
                isinstance(flags, int) and flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND))
            if writing:
                if name == os.devnull:
                    return
                require(type(name) is int and stat.S_ISFIFO(os.fstat(name).st_mode)
                        and len(pipe_opens) < 16, "decision entry regular-file write rejected")
                pipe_opens.append(name)
    sys.addaudithook(audit)
    return commands


def run(scope_name, expected_scope_sha256):
    started = time.monotonic()
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    resource.setrlimit(resource.RLIMIT_CPU, (60, 60))
    resource.setrlimit(resource.RLIMIT_FSIZE, (0, 0))
    def expired(*_):
        raise TimeoutError("admitted decision entry deadline exhausted")
    signal.signal(signal.SIGALRM, expired)
    signal.setitimer(signal.ITIMER_REAL, 60)
    scope, scope_sha, work = admit(scope_name, expected_scope_sha256)
    remaining = min(scope["maximum_entry_seconds"] - (time.monotonic() - started),
                    scope["deadline_unix"] - time.time())
    require(remaining > 0, "entry admission expired during bootstrap")
    signal.setitimer(signal.ITIMER_REAL, remaining)
    consume_parent_token(scope, scope_sha, work)
    require(all(stat.S_ISFIFO(os.fstat(fd).st_mode) for fd in (1, 2)),
            "entry output must use owned metered parent pipes")
    sys.path.insert(0, str(ROOT))
    from tools.host_lease import inherited

    require(inherited(ROOT / "runs/TIMED_STRENGTH.lock"), "real inherited parent host lease required")
    commands = install_read_only_guard(scope)
    from verification.final_projection import verify

    report = verify(ROOT / scope["evidence_root"], ROOT, scope["product_commit"],
                    scope["inputs_sha256"], maximum_seconds=remaining,
                    audit_trust_path=scope.get("audit_trust_path"),
                    expected_audit_trust_sha256=scope.get("expected_audit_trust_sha256"))
    require(type(report["exit_code"]) is int and report["exit_code"] in {0, 2}
            and report["full_acceptance"] is (report["exit_code"] == 0),
            "decision entry report and actual exit disagree")
    report["entry_admission"] = {"scope_sha256": scope_sha, "parent_token_consumed": True,
                                 "inherited_host_lease": True, "read_only_git_calls": len(commands)}
    signal.setitimer(signal.ITIMER_REAL, 0)
    return report


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--scope", required=True)
    parser.add_argument("--expected-scope-sha256", required=True)
    args = parser.parse_args(argv)
    try:
        report = run(args.scope, args.expected_scope_sha256)
        print(json.dumps(report, allow_nan=False))
        return report["exit_code"]
    except (ValueError, KeyError, TypeError, OSError, TimeoutError, struct.error,
            subprocess.SubprocessError) as error:
        print(json.dumps({"status": "rejected", "reason": str(error), "full_acceptance": False}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
