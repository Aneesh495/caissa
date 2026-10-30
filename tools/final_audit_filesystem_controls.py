"""One fresh finite owner for the eighteen synthetic receipt filesystem cases."""

import argparse
import builtins
import fcntl
import hashlib
import importlib.util
import io
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
    for key, maximum in ((resource.RLIMIT_CPU, 30), (resource.RLIMIT_FSIZE, 512000)):
        hard = resource.getrlimit(key)[1]
        limit = maximum if hard == resource.RLIM_INFINITY else min(maximum, hard)
        require(limit > 0, "inherited filesystem-owner limit exhausted")
        resource.setrlimit(key, (limit, limit))
    signal.signal(signal.SIGALRM, lambda *_: (_ for _ in ()).throw(TimeoutError("filesystem control deadline")))
    signal.setitimer(signal.ITIMER_REAL, 45)
    os.umask(0o077)
    scope_path = Path(scope_name).absolute()
    require(scope_path == scope_path.resolve() and scope_path.is_relative_to(ROOT / "work")
            and scope_path.stat().st_size <= 65536 and scope_path.stat().st_nlink == 1
            and stat.S_IMODE(scope_path.stat().st_mode) == 0o600, "private finite filesystem scope required")
    raw = scope_path.read_bytes()
    scope = json.loads(raw)
    require(hashlib.sha256(raw).hexdigest() == expected_scope_sha256
            and scope["schema"] == "caissa-final-audit-filesystem-controls-scope-v1"
            and scope["status"] == "admitted" and scope["maximum_owner_starts"] == 1
            and scope["controls"] == 18 and time.time() < scope["deadline_unix"] <= scope["parent_deadline_unix"]
            and sys.dont_write_bytecode and sys.flags.safe_path and Path.cwd().resolve() == ROOT,
            "filesystem admission, count, startup or deadline differs")
    signal.setitimer(signal.ITIMER_REAL, min(45, scope["deadline_unix"] - time.time()))
    authority = ROOT / scope["authority_path"]
    require(authority == authority.resolve() and authority.stat().st_size <= 16384
            and hashlib.sha256(authority.read_bytes()).hexdigest() == scope["authority_sha256"]
            and json.loads(authority.read_bytes())["deadline_unix"] == scope["parent_deadline_unix"],
            "filesystem human continuation differs from independent admission")
    for key in ("native_starts", "browser_starts", "compiler_starts", "training_starts",
                "inference_starts", "game_starts", "new_parallel_starts", "extra_parallel_active_seconds"):
        require(type(scope[key]) is int and scope[key] == 0, "filesystem controls admit metadata only")
    work, fixtures = scope_path.parent, scope_path.parent / "fixtures"
    require(not fixtures.exists() and not (work / "STARTED.json").exists(), "filesystem namespace already consumed")
    lease = (ROOT / "runs/TIMED_STRENGTH.lock").open("r+")
    fcntl.flock(lease, fcntl.LOCK_EX | fcntl.LOCK_NB)
    metadata = {work / name for name in ("STARTED.json", "FILESYSTEM_CONTROLS.json", "METADATA_USAGE.json", "FAILED.json")}
    file_names = {"work/private.json", "work/inside-bundle/receipt.json", "work/public-mode.json",
                  "work/empty.json", "work/oversized.json", "work/real-parent/receipt.json",
                  "work/hard-source.json", "work/caller-pass.json", "work/changing.json"}
    files = {fixtures / name for name in file_names}
    dirs = {fixtures, *(fixtures / n for n in ("work", "evidence", "work/inside-bundle",
                                               "work/real-parent", "work/receipt-directory"))}
    links = {fixtures / "work/final-link.json": "private.json", fixtures / "work/linked-parent": "real-parent"}
    hard_pair = (fixtures / "work/hard-source.json", fixtures / "work/hard-alias.json")
    fifo = fixtures / "work/receipt-fifo"
    changing = fixtures / "work/changing.json"
    charged, written, appends, fifo_count = 0, 0, 0, 0
    chmods, made_dirs, made_links, hard_links, created_files = {}, set(), set(), [], set()
    originals = builtins.open, io.open, os.write, os.mkfifo

    def audit(event, args):
        if event.startswith("socket.") or event in {
            "subprocess.Popen", "os.system", "os.posix_spawn", "os.exec", "os.fork", "os.forkpty",
            "os.remove", "os.rename", "os.rmdir", "os.truncate", "os.chown", "os.utime", "os.chdir"
        }:
            raise ValueError("filesystem controls reject processes, network and unrelated mutation")
        if event == "os.mkdir":
            target = Path(args[0]).absolute()
            require(target in dirs and target not in made_dirs and target == target.resolve(),
                    "filesystem fixture directory escaped exact inventory")
            made_dirs.add(target)
        if event == "os.symlink":
            target = Path(args[1]).absolute()
            require(target in links and links[target] == args[0] and target not in made_links,
                    "filesystem synthetic link differs")
            made_links.add(target)
        if event == "os.link":
            require((Path(args[0]).absolute(), Path(args[1]).absolute()) == hard_pair and not hard_links,
                    "filesystem hardlink differs")
            hard_links.append(True)
        if event == "os.chmod":
            target = Path(args[0]).absolute()
            expected = [0o600, 0o644, 0o600] if target == fixtures / "work/public-mode.json" else [0o600]
            count = chmods.get(target, 0)
            require(target in files and count < len(expected) and args[1] == expected[count],
                    "filesystem fixture permission change differs")
            chmods[target] = count + 1
        if event == "open":
            name, mode, flags = args
            writing = isinstance(mode, str) and any(c in mode for c in "wax+") or (
                isinstance(flags, int) and flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND))
            if writing:
                require(isinstance(name, str), "raw filesystem descriptor write rejected")
                target = Path(name).absolute()
                require(target == target.resolve() and (target in metadata and mode == "x"
                        or target in files and flags & os.O_EXCL and flags & os.O_CREAT
                        or target == changing and flags & os.O_APPEND), "filesystem writer escaped exact names")
            elif isinstance(name, str) and Path(name).absolute().is_relative_to(ROOT) and name.endswith(".pyc"):
                raise FileNotFoundError("filesystem owner requires pinned source bytes")

    sys.addaudithook(audit)

    class FixtureStream:
        def __init__(self, stream, path):
            self.stream, self.path = stream, path

        def write(self, body):
            nonlocal charged
            require(isinstance(body, bytes) and charged + len(body) <= 32768
                    and self.stream.tell() + len(body) <= 8193, "filesystem payload credits exhausted")
            charged += len(body)
            return self.stream.write(body)

        def __getattr__(self, name):
            require(name not in {"buffer", "raw", "detach", "seek", "truncate", "writelines"},
                    "filesystem raw or sparse writer bypass rejected")
            return getattr(self.stream, name)

        def __enter__(self):
            return self

        def __exit__(self, *_):
            self.stream.close()

    def wrap(original):
        def opened(file, mode="r", *args, **kwargs):
            nonlocal appends
            if any(c in mode for c in "wax+") and not isinstance(file, int) and Path(file).absolute() in files:
                target = Path(file).absolute()
                if mode == "xb":
                    require(target not in created_files, "filesystem initial writer repeated")
                    created_files.add(target)
                else:
                    require(mode == "ab" and target == changing and appends == 0,
                            "filesystem append is not the one synchronized mutation")
                    appends += 1
                return FixtureStream(original(file, mode, *args, **kwargs), target)
            return original(file, mode, *args, **kwargs)
        return opened

    def raw_write(fd, body):
        require(not stat.S_ISREG(os.fstat(fd).st_mode), "filesystem raw descriptor writer rejected")
        return originals[2](fd, body)

    def mkfifo(path, mode=0o666, *, dir_fd=None):
        nonlocal fifo_count
        require(Path(path).absolute() == fifo and mode == 0o600 and dir_fd is None and fifo_count == 0,
                "filesystem FIFO creation escaped exact inventory")
        fifo_count += 1
        return originals[3](path, mode)

    def put(name, value):
        nonlocal written
        body = json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n"
        require(len(body.encode()) <= 512000 and written + len(body.encode()) <= scope["control_bytes"],
                "filesystem metadata reservation exhausted")
        written += len(body.encode())
        with (work / name).open("x") as stream:
            stream.write(body)
            stream.flush()
            os.fsync(stream.fileno())

    failure = None
    try:
        put("STARTED.json", {"scope_sha256": expected_scope_sha256, "owner_pid": os.getpid(), "owner_start": 1})
        require(sys.executable == scope["python_command"]
                and hashlib.sha256(Path(sys.executable).read_bytes()).hexdigest() == scope["interpreter_sha256"],
                "filesystem interpreter differs")
        total = 0
        for name, pin in scope["source_bindings"].items():
            target = ROOT / name
            require(target == target.resolve() and target.stat().st_size <= 4 * 1024**2,
                    "filesystem pinned source is linked or excessive")
            raw = target.read_bytes()
            total += len(raw)
            require(total <= 16 * 1024**2 and hashlib.sha256(raw).hexdigest() == pin, "filesystem source pin differs")
        builtins.open, io.open, os.write, os.mkfifo = wrap(originals[0]), wrap(originals[1]), raw_write, mkfifo
        fixtures.mkdir()
        sys.path.insert(0, str(ROOT))
        spec = importlib.util.spec_from_file_location("admitted_final_audit_filesystem", ROOT / "tests/final_audit_trust_filesystem.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        result = module.run_controls(fixtures)
        require(result["controls"] == len(result["cases"]) == 18
                and result["fixture_payload_bytes_written"] == charged
                and result["full_acceptance"] is False and created_files == files
                and made_dirs == dirs and made_links == set(links) and hard_links == [True]
                and appends == fifo_count == 1 and len(chmods) == len(files),
                "filesystem actual cases, bytes or operation inventory differs")
        for name, pin in scope["source_bindings"].items():
            require(hashlib.sha256((ROOT / name).read_bytes()).hexdigest() == pin, "filesystem source changed")
        require(time.time() < scope["deadline_unix"], "filesystem owner deadline exhausted")
        put("FILESYSTEM_CONTROLS.json", result)
    except BaseException as error:
        failure = {"type": type(error).__name__, "reason": str(error)[:2048]}
        put("FAILED.json", {"failure": failure, "full_acceptance": False})
        raise
    finally:
        builtins.open, io.open, os.write, os.mkfifo = originals
        usage = resource.getrusage(resource.RUSAGE_SELF)
        put("METADATA_USAGE.json", {"closed": True, "failure": failure, "scope_sha256": expected_scope_sha256,
            "elapsed_seconds": time.monotonic() - started, "observed_self_cpu_seconds": usage.ru_utime + usage.ru_stime,
            "fixture_payload_bytes_written": charged, "full_R12_complete": False, "full_acceptance": False})
        lease.close()
        signal.setitimer(signal.ITIMER_REAL, 0)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("scope")
    parser.add_argument("expected_scope_sha256")
    args = parser.parse_args()
    main(args.scope, args.expected_scope_sha256)
