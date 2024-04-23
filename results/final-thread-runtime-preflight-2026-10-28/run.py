"""One scoped functional prerequisite for a new exact-option race check."""

import fcntl
import hashlib
import json
import os
from pathlib import Path
import resource
import select
import signal
import subprocess
import sys
import time
import zipfile


def require(value, reason):
    if not value:
        raise ValueError(reason)


def main(scope_path):
    started = time.monotonic()
    scope_path = Path(scope_path).resolve()
    scope = json.loads(scope_path.read_text())
    root, output = Path(scope["root"]), scope_path.parent
    require(time.time() < scope["deadline_unix"] and not (output / "STARTED.json").exists(), "one fresh finite preflight required")
    lease = (root / "runs/TIMED_STRENGTH.lock").open("r+")
    fcntl.flock(lease.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    resource.setrlimit(resource.RLIMIT_FSIZE, (8 * 1024**2, 8 * 1024**2))

    def stop(*_):
        raise TimeoutError("preflight deadline exhausted")

    signal.signal(signal.SIGALRM, stop)
    signal.setitimer(signal.ITIMER_REAL, min(30, scope["deadline_unix"] - time.time()))
    (output / "STARTED.json").write_text(json.dumps({"unix": time.time()}) + "\n")
    for name, expected in scope["input_bindings"].items():
        path = Path(name) if name.startswith("/") else root / name
        require(hashlib.sha256(path.read_bytes()).hexdigest() == expected, "pinned preflight input differs")
    with zipfile.ZipFile(root / scope["archive"]) as archive:
        data = archive.read(scope["archive_member"])
    require(len(data) < 1_000_000 and hashlib.sha256(data).hexdigest() == scope["instrumented_engine_sha256"], "instrumented program differs")
    engine = output / "caissa-tsan"
    engine.write_bytes(data)
    engine.chmod(0o700)
    runtime_data = Path(scope["runtime_source"]).read_bytes()
    require(len(runtime_data) < 5_000_000, "runtime exceeds prepaid copy")
    runtime = output / "libclang_rt.tsan_osx_dynamic.dylib"
    runtime.write_bytes(runtime_data)
    runtime.chmod(0o600)
    runtime_sha = hashlib.sha256(runtime_data).hexdigest()
    network = root / scope["network"]
    stderr_path = output / "native.stderr"
    result = {"status": "failed_preflight", "instrumented_engine_sha256": scope["instrumented_engine_sha256"], "network_sha256": scope["input_bindings"][scope["network"]], "local_runtime_sha256": runtime_sha, "runtime_source_copy": True, "original_archive_runtime_reproduced": False, "native_starts": 1, "games_started": 0, "searched_node_budget": 128, "full_R03_completed": False, "full_acceptance": False}
    process, captured = None, bytearray()
    stderr_prefix, critical, pending = bytearray(), bytearray(), bytearray()
    stderr_digest, stderr_total, discarded, loaded_runtime = hashlib.sha256(), 0, 0, False
    open_streams = set()

    def stderr_line(line):
        nonlocal loaded_runtime
        loaded_runtime |= str(runtime).encode() in line
        if not line.startswith(b"dyld["):
            require(len(critical) + len(line) <= 65536, "non-telemetry diagnostics exceed retained bound")
            critical.extend(line)

    def pump(timeout=0.1):
        nonlocal stderr_total, discarded
        ready, _, _ = select.select(list(open_streams), [], [], timeout)
        for stream in ready:
            chunk = os.read(stream.fileno(), 65536)
            if not chunk:
                open_streams.remove(stream)
                continue
            if stream is process.stdout:
                captured.extend(chunk)
                require(len(captured) <= 1_000_000, "native output exceeds prepaid bound")
            else:
                stderr_digest.update(chunk)
                stderr_total += len(chunk)
                keep = min(len(chunk), 65536 - len(stderr_prefix))
                stderr_prefix.extend(chunk[:keep])
                discarded += len(chunk) - keep
                pending.extend(chunk)
                while b"\n" in pending:
                    line, _, tail = pending.partition(b"\n")
                    pending[:] = tail
                    stderr_line(line + b"\n")
    try:
        env = dict(os.environ, DYLD_LIBRARY_PATH=str(output), DYLD_PRINT_LIBRARIES="1", TSAN_OPTIONS="halt_on_error=1:exitcode=66")
        process = subprocess.Popen([str(engine)], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env, start_new_session=True, bufsize=0, preexec_fn=lambda: resource.setrlimit(resource.RLIMIT_FSIZE, (65536, 65536)))
        open_streams.update([process.stdout, process.stderr])

        def send(text):
            process.stdin.write(text.encode())
            process.stdin.flush()

        def wait_for(marker):
            deadline = min(scope["deadline_unix"], time.time() + 10)
            while marker not in captured:
                require(time.time() < deadline and process.poll() is None, "native prerequisite did not complete")
                pump()

        send("uci\n")
        wait_for(b"uciok")
        send("setoption name Hash value 16\nsetoption name Threads value 8\nsetoption name EvalFile value " + str(network) + "\nsetoption name Use Neural value true\nsetoption name Neural Weight value 10\nsetoption name Lazy Neural value true\nsetoption name Evaluation Cache value true\nsetoption name Tactical Generation value true\nsetoption name Neural Bounds value false\nsetoption name Ordering Hints value false\nisready\n")
        wait_for(b"readyok")
        send("position startpos\ngo nodes 128\n")
        wait_for(b"bestmove ")
        best = next(line.split()[1].decode() for line in captured.splitlines() if line.startswith(b"bestmove "))
        require(len(best) in [4, 5] and best != "0000" and b"info string error" not in captured, "native option/model/search prerequisite rejected")
        send("quit\n")
        process.stdin.close()
        deadline = time.time() + 5
        while process.poll() is None:
            require(time.time() < deadline, "native prerequisite quit deadline exhausted")
            pump()
        while open_streams:
            pump()
        if pending:
            stderr_line(pending)
            pending.clear()
        require(process.returncode == 0, "native prerequisite exited unsuccessfully")
        require(loaded_runtime and b"WARNING: ThreadSanitizer" not in critical and b"ThreadSanitizer: CHECK failed" not in critical and b"FATAL: ThreadSanitizer" not in critical, "loaded runtime witness missing or sanitizer failure")
        result.update(status="passed_runtime_prerequisite_only", native_exit=0, bestmove=best, applied_configuration={"Threads": 8, "Hash": 16, "Use Neural": True, "Neural Weight": 10, "Lazy Neural": True, "Evaluation Cache": True, "Tactical Generation": True, "Neural Bounds": False, "Ordering Hints": False}, local_runtime_loaded_witness=True)
    except (ValueError, OSError, TimeoutError, subprocess.SubprocessError) as error:
        result["reason"] = str(error)
    finally:
        if process is not None:
            if process.poll() is None:
                try:
                    os.killpg(process.pid, signal.SIGTERM)
                    process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait(timeout=2)
            result["native_exit"] = process.returncode
            while open_streams:
                pump()
            if pending:
                stderr_line(pending)
            if process.stdout is not None:
                process.stdout.close()
            if process.stderr is not None:
                process.stderr.close()
        (output / "native.stdout").write_bytes(captured)
        (output / "native.stdout").chmod(0o600)
        result["elapsed_seconds"] = time.monotonic() - started
        result["stdout_sha256"] = hashlib.sha256(captured).hexdigest()
        stderr_path.write_bytes(stderr_prefix)
        stderr_path.chmod(0o600)
        (output / "critical.stderr").write_bytes(critical)
        (output / "critical.stderr").chmod(0o600)
        result.update(stderr_full_sha256=stderr_digest.hexdigest(), stderr_total_bytes=stderr_total, retained_stderr_bytes=len(stderr_prefix), optional_diagnostic_bytes_not_retained=discarded, critical_stderr_bytes=len(critical))
        (output / "PREFLIGHT.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({k: result[k] for k in ["status", "native_starts", "games_started", "elapsed_seconds", "full_R03_completed", "full_acceptance"]}))
    if result["status"] != "passed_runtime_prerequisite_only":
        raise SystemExit(1)


if __name__ == "__main__":
    main(sys.argv[1])
