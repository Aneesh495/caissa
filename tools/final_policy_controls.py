"""One separately admitted execution of the 23+9 new in-memory policy cases."""

import argparse
import fcntl
import hashlib
import importlib.util
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


def main(scope_name, expected_scope_sha256):
    started = time.monotonic()
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    inherited_cpu = resource.getrlimit(resource.RLIMIT_CPU)[1]
    cpu = 30 if inherited_cpu == resource.RLIM_INFINITY else min(30, inherited_cpu)
    inherited_file = resource.getrlimit(resource.RLIMIT_FSIZE)[1]
    file_limit = 512000 if inherited_file == resource.RLIM_INFINITY else min(512000, inherited_file)
    require(cpu > 0 and file_limit >= 512000, "inherited policy owner limits are insufficient")
    resource.setrlimit(resource.RLIMIT_CPU, (cpu, cpu))
    resource.setrlimit(resource.RLIMIT_FSIZE, (file_limit, file_limit))
    signal.signal(signal.SIGALRM, lambda *_: (_ for _ in ()).throw(TimeoutError("policy owner deadline exhausted")))
    signal.setitimer(signal.ITIMER_REAL, 45)
    os.umask(0o077)
    path = Path(scope_name).absolute()
    require(path == path.resolve() and path.is_relative_to(ROOT / "work")
            and path.name == "SCOPE.json" and path.stat().st_size <= 65536
            and stat.S_IMODE(path.stat().st_mode) == 0o600 and path.stat().st_nlink == 1,
            "one private independently pinned policy scope required")
    raw = path.read_bytes()
    scope = json.loads(raw)
    require(hashlib.sha256(raw).hexdigest() == expected_scope_sha256
            and scope["schema"] == "caissa-final-policy-controls-scope-v1" and scope["status"] == "admitted"
            and time.time() < scope["deadline_unix"] <= scope["parent_deadline_unix"]
            and scope["maximum_owner_starts"] == 1 and scope["controls"] == [23, 9]
            and sys.dont_write_bytecode and sys.flags.safe_path and Path.cwd().resolve() == ROOT,
            "policy scope, count, safe startup or fixed deadline differs")
    signal.setitimer(signal.ITIMER_REAL, min(45, scope["deadline_unix"] - time.time()))
    authority = ROOT / scope["authority_path"]
    require(authority == authority.resolve() and authority.stat().st_size <= 16384
            and hashlib.sha256(authority.read_bytes()).hexdigest() == scope["authority_sha256"]
            and json.loads(authority.read_bytes())["deadline_unix"] == scope["parent_deadline_unix"],
            "policy owner human continuation differs from independent admission")
    for key in ("native_starts", "browser_starts", "compiler_starts", "training_starts",
                "inference_starts", "game_starts", "new_parallel_starts", "extra_parallel_active_seconds"):
        require(type(scope[key]) is int and scope[key] == 0, "policy owner admits metadata only")
    work = path.parent
    require(not (work / "STARTED.json").exists(), "policy owner namespace already consumed")
    lease = (ROOT / "runs/TIMED_STRENGTH.lock").open("r+")
    fcntl.flock(lease, fcntl.LOCK_EX | fcntl.LOCK_NB)
    allowed = {work / name for name in ("STARTED.json", "PROJECTION_POLICY.json", "AUDIT_TRUST_POLICY.json",
                                       "METADATA_USAGE.json", "FAILED.json")}
    written, writers = 0, set()

    def audit(event, args):
        if event.startswith("socket.") or event in {
            "subprocess.Popen", "os.system", "os.posix_spawn", "os.exec", "os.fork", "os.forkpty",
            "os.link", "os.symlink", "os.remove", "os.rename", "os.mkdir", "os.rmdir",
            "os.truncate", "os.chmod", "os.chown", "os.utime", "os.chdir"
        }:
            raise ValueError("policy owner rejects children, network and unrelated mutation")
        if event == "open":
            name, mode, flags = args
            writing = isinstance(mode, str) and any(c in mode for c in "wax+") or (
                isinstance(flags, int) and flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND))
            if writing:
                require(isinstance(name, str) and Path(name).absolute() in allowed
                        and Path(name).absolute() == Path(name).resolve() and mode == "x",
                        "policy writer escaped exact exclusive output names")
            elif isinstance(name, str) and Path(name).absolute().is_relative_to(ROOT) and name.endswith(".pyc"):
                raise FileNotFoundError("policy owner requires pinned source, not cached project bytecode")

    sys.addaudithook(audit)

    def put(name, value):
        nonlocal written
        body = json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n"
        require(name not in writers and len(body.encode()) <= 512000
                and written + len(body.encode()) <= scope["control_bytes"], "policy metadata reservation exhausted")
        writers.add(name)
        written += len(body.encode())
        with (work / name).open("x") as stream:
            stream.write(body)
            stream.flush()
            os.fsync(stream.fileno())

    failure = None
    try:
        put("STARTED.json", {"owner_pid": os.getpid(), "scope_sha256": expected_scope_sha256,
                            "owner_start": 1, "unix": time.time()})
        executable = Path(sys.executable).resolve()
        require(sys.executable == scope["python_command"] and str(executable) == scope["interpreter"]
                and hashlib.sha256(executable.read_bytes()).hexdigest() == scope["interpreter_sha256"],
                "policy interpreter identity differs")
        total = 0
        for name, expected in scope["source_bindings"].items():
            target = ROOT / name
            require(target == target.resolve() and stat.S_ISREG(target.stat().st_mode)
                    and target.stat().st_nlink == 1 and target.stat().st_size <= 4 * 1024**2,
                    "policy source is linked or excessive")
            source = target.read_bytes()
            total += len(source)
            require(total <= 16 * 1024**2 and hashlib.sha256(source).hexdigest() == expected,
                    "policy source differs from independent pin")
        sys.path.insert(0, str(ROOT))
        for name, output, count in (("final_projection_policy", "PROJECTION_POLICY.json", 23),
                                    ("final_audit_trust_policy", "AUDIT_TRUST_POLICY.json", 9)):
            spec = importlib.util.spec_from_file_location("admitted_" + name, ROOT / "tests" / (name + ".py"))
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            result = module.run_controls()
            require(result["controls"] == len(result["cases"]) == count
                    and result["full_acceptance"] is False, "actual new policy case inventory differs")
            put(output, result)
        for name, expected in scope["source_bindings"].items():
            require(hashlib.sha256((ROOT / name).read_bytes()).hexdigest() == expected,
                    "policy source changed during actual controls")
        require(time.time() < scope["deadline_unix"], "policy owner fixed deadline exhausted")
    except BaseException as error:
        failure = {"type": type(error).__name__, "reason": str(error)[:2048]}
        put("FAILED.json", {"failure": failure, "full_acceptance": False})
        raise
    finally:
        usage = resource.getrusage(resource.RUSAGE_SELF)
        put("METADATA_USAGE.json", {"closed": True, "failure": failure,
            "scope_sha256": expected_scope_sha256, "elapsed_seconds": time.monotonic() - started,
            "observed_self_cpu_seconds": usage.ru_utime + usage.ru_stime, "control_bytes_written": written,
            "new_native_or_game_starts": 0, "full_R12_complete": False, "full_acceptance": False})
        lease.close()
        signal.setitimer(signal.ITIMER_REAL, 0)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("scope")
    parser.add_argument("expected_scope_sha256")
    args = parser.parse_args()
    main(args.scope, args.expected_scope_sha256)
