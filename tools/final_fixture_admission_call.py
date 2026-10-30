"""Unexecuted bounded constructor caller; requires actual external human review.

The message digest is supplied independently by the trusted caller after reading
the actual human reply. This program cannot establish that provenance itself.
"""

import argparse
import hashlib
import json
import math
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


def read(name, maximum, *, private):
    require(isinstance(name, str) and not name.startswith("/") and "\\" not in name
            and 0 < len(name.encode()) <= 4096
            and all(x not in {"", ".", ".."} for x in name.split("/"))
            and all(32 <= ord(c) != 127 for c in name), "invalid bootstrap input name")
    parts = name.split("/")
    directory = os.open(ROOT, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for part in parts[:-1]:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory)
            os.close(directory)
            directory = child
        fd = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
        with os.fdopen(fd, "rb") as stream:
            before = os.fstat(stream.fileno())
            require(stat.S_ISREG(before.st_mode) and before.st_nlink == 1
                    and 0 < before.st_size <= maximum
                    and (not private or stat.S_IMODE(before.st_mode) == 0o600),
                    "bootstrap input is linked, public or excessive")
            raw = stream.read(maximum + 1)
            after = os.fstat(stream.fileno())
        stamp = lambda s: (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns)
        require(len(raw) == before.st_size and stamp(before) == stamp(after),
                "bootstrap input changed during read")
        return raw
    finally:
        os.close(directory)


def run(request_name, expected_request_sha256, verified_human_message_sha256):
    started = time.monotonic()
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    inherited = resource.getrlimit(resource.RLIMIT_CPU)[1]
    cpu = 30 if inherited == resource.RLIM_INFINITY else min(30, inherited)
    require(cpu > 0, "admission caller inherited CPU limit exhausted")
    resource.setrlimit(resource.RLIMIT_CPU, (cpu, cpu))
    inherited = resource.getrlimit(resource.RLIMIT_FSIZE)[1]
    size = 1024**2 if inherited == resource.RLIM_INFINITY else min(1024**2, inherited)
    require(size >= 1024**2, "admission caller inherited file bound is insufficient")
    resource.setrlimit(resource.RLIMIT_FSIZE, (size, size))

    def expired(*_):
        raise TimeoutError("fixed admission-caller wall limit exhausted")

    signal.signal(signal.SIGALRM, expired)
    signal.setitimer(signal.ITIMER_REAL, 45)
    try:
        require(sys.dont_write_bytecode and sys.flags.safe_path and Path.cwd().resolve() == ROOT
                and all(stat.S_ISFIFO(os.fstat(fd).st_mode) for fd in (1, 2)),
                "admission caller needs safe startup and externally owned output pipes")
        require(request_name.startswith(".agent-local/"), "private independently pinned request required")
        raw = read(request_name, 1024**2, private=True)
        require(hashlib.sha256(raw).hexdigest() == expected_request_sha256,
                "bootstrap request differs from independent pin")

        def pairs(items):
            result = {}
            for key, value in items:
                require(key not in result, "duplicate bootstrap request key")
                result[key] = value
            return result

        def nonfinite(_):
            raise ValueError("nonfinite bootstrap request number")

        request = json.loads(raw, object_pairs_hook=pairs, parse_constant=nonfinite)
        deadline = request["deadline_unix"]
        require(type(deadline) in {int, float} and math.isfinite(deadline), "invalid fixed caller deadline")
        remaining = min(45 - (time.monotonic() - started), deadline - time.time())
        require(remaining > 0, "admission request deadline expired before constructor import")
        signal.setitimer(signal.ITIMER_REAL, remaining)
        names = {"tools/final_fixture_admission_call.py", "tools/final_fixture_admission.py",
                 "tools/parallel_storage_quota.py", "tools/storage_budget.py"}
        for name in names:
            require(hashlib.sha256(read(name, 4 * 1024**2, private=False)).hexdigest()
                    == request["source_bindings"][name], "pinned constructor bootstrap source changed")
        work_name = request["work"]
        require(isinstance(work_name, str) and len(work_name.split("/")) == 2
                and work_name.startswith("work/") and work_name.split("/")[1] not in {"", ".", ".."},
                "one fresh direct work namespace required")
        work, scope = ROOT / work_name, ROOT / work_name / "SCOPE.json"
        require(work == work.resolve() and not work.exists(), "constructor namespace already consumed")
        directories, writers = [], []

        def audit(event, args):
            if event.startswith("socket.") or event in {
                "subprocess.Popen", "os.system", "os.posix_spawn", "os.exec", "os.link", "os.symlink",
                "os.remove", "os.rename", "os.rmdir", "os.truncate", "os.chmod", "os.chown", "os.utime",
                "os.chdir", "os.fork", "os.forkpty"
            }:
                raise ValueError("constructor caller rejects processes, network and unrelated mutation")
            if event == "os.mkdir":
                require(Path(args[0]).absolute() == work and not directories,
                        "only one exact scope directory may be created")
                directories.append(True)
            if event == "open":
                name, mode, flags = args
                writing = isinstance(mode, str) and any(c in mode for c in "wax+")
                writing = writing or isinstance(flags, int) and flags & (
                    os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND)
                if writing:
                    require(isinstance(name, str) and Path(name).absolute() == scope
                            and isinstance(flags, int) and flags & os.O_EXCL and flags & os.O_CREAT
                            and not flags & (os.O_TRUNC | os.O_APPEND) and not writers,
                            "only one exclusive bounded scope-file write is admitted")
                    writers.append(True)

        sys.addaudithook(audit)
        sys.path.insert(0, str(ROOT))
        from tools.final_fixture_admission import construct

        result = construct(request_name, expected_request_sha256, verified_human_message_sha256)
        own = resource.getrusage(resource.RUSAGE_SELF)
        children = resource.getrusage(resource.RUSAGE_CHILDREN)
        used = own.ru_utime + own.ru_stime
        require(directories == writers == [True] and used <= cpu
                and children.ru_utime + children.ru_stime == 0
                and time.monotonic() - started <= 45 and time.time() < deadline
                and result["owner_started"] is False and result["seed_created"] is False
                and result["controls_run"] == 0 and result["full_R12_complete"] is False
                and result["full_acceptance"] is False,
                "actual constructor-only counters, result or fixed limits differ")
        return {**result, "status": "constructed_scope_only", "observed_self_cpu_seconds": used,
                "caller_exit_independently_checked": False}
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--request", required=True)
    parser.add_argument("--expected-request-sha256", required=True)
    parser.add_argument("--verified-human-message-sha256", required=True)
    args = parser.parse_args()
    try:
        result = run(args.request, args.expected_request_sha256, args.verified_human_message_sha256)
        raw = json.dumps(result, allow_nan=False)
        require(len(raw.encode()) <= 4096, "constructor result output exceeded its bound")
    except Exception as error:
        print(json.dumps({"status": "rejected", "error_type": type(error).__name__,
                          "partial_scope_must_be_independently_inspected": True,
                          "full_acceptance": False}))
        return 1
    print(raw)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
