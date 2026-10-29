"""One bounded reader-only correction on the retained exact-neural transcript."""

import copy
import fcntl
import hashlib
import json
import os
from pathlib import Path
import resource
import signal
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def require(value, reason):
    if not value:
        raise ValueError(reason)


def controls(profile, expected):
    from verification.thread_runtime import inspect_events
    rows = [{"event": "open", "session": 0, "kind": "release", "threads": 1,
             "engine_sha256": expected["release_engine_sha256"],
             "network_sha256": expected["network_sha256"], "runtime_sha256": None}]
    stamp = 0

    def emit(event, text):
        nonlocal stamp
        stamp += 1
        rows.append({"event": event, "session": 0, "ns": stamp, "text": text})

    emit("send", "uci")
    emit("recv", "uciok")
    options = {"Hash": 16, "Threads": 1, "EvalFile": expected["network_path"],
               **{k: v for k, v in profile["options"].items() if k != "Hash"}}
    for key, value in options.items():
        value = str(value).lower() if type(value) is bool else str(value)
        emit("send", "setoption name " + key + " value " + value)
    emit("send", "isready")
    emit("recv", "info string network " + expected["network_identity"])
    emit("recv", "readyok")

    def check(case, items, reason):
        items = [dict(row) for row in items]
        for i, row in enumerate(items):
            if "ns" in row:
                row["ns"] = i + 1
        try:
            inspect_events(iter(items), profile, expected)
        except ValueError as error:
            require(str(error) == reason, case + ": unexpected rejection " + str(error))
        else:
            raise ValueError(case + ": incomplete/forged prefix accepted")
        return {"case": case, "status": "checked", "expected_rejection": reason}

    ack = next(i for i, r in enumerate(rows) if r.get("text", "").startswith("info string network"))
    checks = [check("correct_model_acknowledgement_prefix_is_not_full_sample", copy.deepcopy(rows), "incomplete full thread runtime evidence")]
    wrong = copy.deepcopy(rows)
    wrong[ack]["text"] = "info string network " + "0" * 64
    checks.append(check("wrong_model_identity", wrong, "wrong, duplicate or unsolicited model acknowledgement"))
    checks.append(check("missing_model_acknowledgement", copy.deepcopy(rows[:ack] + rows[ack+1:]), "ready before full applied options and model acknowledgement"))
    checks.append(check("duplicate_model_acknowledgement", copy.deepcopy(rows[:ack] + [rows[ack]] + rows[ack:]), "wrong, duplicate or unsolicited model acknowledgement"))
    checks.append(check("model_acknowledgement_before_EvalFile", copy.deepcopy(rows[:3] + [rows[ack]] + rows[3:ack] + rows[ack+1:]), "wrong, duplicate or unsolicited model acknowledgement"))
    checks.append(check("late_model_acknowledgement", copy.deepcopy(rows + [rows[ack]]), "wrong, duplicate or unsolicited model acknowledgement"))
    unknown = copy.deepcopy(rows)
    unknown[ack]["text"] = "info string unexpected status"
    checks.append(check("unknown_unsolicited_info_remains_rejected", unknown, "stale or unrequested search info"))
    error = copy.deepcopy(rows)
    error[ack]["text"] = "info string error load EvalFile before enabling neural evaluation"
    checks.append(check("native_model_error_remains_fatal", error, "native rejected applied model/options/protocol"))
    return checks


def main(path):
    os.umask(0o077)
    started = time.monotonic()
    path = Path(path).resolve()
    scope = json.loads(path.read_text())
    output = path.parent
    require(scope["status"] == "admitted" and time.time() < scope["deadline_unix"] and scope["native_starts"] == 0 and not (output / "STARTED.json").exists(), "one fresh reader-only invocation required")
    lease = (ROOT / "runs/TIMED_STRENGTH.lock").open("r+")
    fcntl.flock(lease.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    resource.setrlimit(resource.RLIMIT_CPU, (60, 60))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    resource.setrlimit(resource.RLIMIT_FSIZE, (131072, 131072))

    def stop(*_):
        raise TimeoutError("reader correction deadline exhausted")

    signal.signal(signal.SIGALRM, stop)
    signal.setitimer(signal.ITIMER_REAL, min(60, scope["deadline_unix"] - time.time()))
    names = {"STARTED.json", "THREAD_RUNTIME.json", "THREAD_RUNTIME.json.tmp", "CONTROLS.json", "READER_JOIN.json"}

    def audit(event, args):
        if event.startswith("socket.") or event in {"subprocess.Popen", "os.system", "os.posix_spawn", "os.exec"}:
            raise RuntimeError("reader correction prohibits processes and network")
        if event == "open":
            name, mode, flags = args
            writing = (isinstance(mode, str) and any(c in mode for c in "wax+")) or (isinstance(flags, int) and flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND))
            if writing:
                require(not isinstance(name, int) and Path(name).absolute() == Path(name).resolve() and Path(name).parent == output and Path(name).name in names, "reader write escaped bounded namespace")

    sys.addaudithook(audit)
    (output / "STARTED.json").write_text(json.dumps({"unix": time.time()}) + "\n")
    require(str(Path(sys.executable).resolve()) == scope["interpreter"], "reader interpreter differs")
    for name, sha in scope["source_bindings"].items():
        p = ROOT / name
        require(not p.is_symlink() and hashlib.sha256(p.read_bytes()).hexdigest() == sha, "bound reader input differs: " + name)
    require(hashlib.sha256(Path(sys.executable).read_bytes()).hexdigest() == scope["interpreter_sha256"], "reader interpreter bytes differ")
    original = json.loads((ROOT / scope["original_scope"]).read_text())
    run = Path(original["output"])
    profile = json.loads(Path(original["profile"]).read_text())
    network = Path(original["network"]).read_bytes()
    identity = network[40:104].decode("ascii")
    require(len(identity) == 64 and all(c in "0123456789abcdef" for c in identity), "network header identity invalid")
    expected = {"release_engine_sha256": original["engine_sha256"], "instrumented_engine_sha256": original["instrumented_engine_sha256"], "network_sha256": original["network_sha256"], "runtime_sha256": original["instrumented_runtime_sha256"], "network_identity": identity, "network_path": original["network"], "runtime_path": original["instrumented_runtime"]}
    checked = controls(profile, expected)
    (output / "CONTROLS.json").write_text(json.dumps({"status": "passed", "controls": checked, "native_starts": 0, "original_closed_controls_rerun": False}, indent=2) + "\n")
    from verification.thread_runtime import verify
    verify(original, output)
    producer = json.loads((run / "produce.json").read_text())
    require(producer["exit"] == 0 and producer["reason"] == "completed" and producer["cleanup_warnings"] == [], "original producer stage failed")
    require(hashlib.sha256((run / producer["log"]).read_bytes()).hexdigest() == producer["log_sha256"], "original producer log differs")
    writes = json.loads((ROOT / scope["original_write_ledger"]).read_text())
    active = json.loads((run / "ACTIVE_USAGE.json").read_text())
    require(writes["closed"] is True and not writes.get("failure") and writes["native_starts"] == 8 and writes["release_starts"] == writes["instrumented_starts"] == 4 and active["closed"] is True, "original owner/start/ledger closure incomplete")
    native_boundary = json.loads((ROOT / "results/final-core-runtime-join-2026-10-28/BOUNDARY.json").read_text())
    for name, sha in native_boundary["native_source_sha256"].items():
        require(hashlib.sha256((ROOT / name).read_bytes()).hexdigest() == sha and bool((ROOT / name).stat().st_mode & 0o111) == (native_boundary["native_source_modes"][name] == "100755"), "native source/mode relationship differs")
    result = {"status": "passed_reader_only_correction", "actual_transcript_from_second_owner": True, "original_first_and_second_failed_owner_receipts_preserved": True, "original_producer_exit": producer["exit"], "original_native_starts": writes["native_starts"], "new_native_starts": 0, "games": 0, "matched_native_files": len(native_boundary["native_source_sha256"]), "reader_result_sha256": hashlib.sha256((output / "THREAD_RUNTIME.json").read_bytes()).hexdigest(), "controls": len(checked), "elapsed_seconds": time.monotonic() - started, "cumulative_active_seconds": scope["prior_active_seconds"] + time.monotonic() - started, "original_compiler_runtime_closure_established": False, "full_G10_certified": False, "full_acceptance": False}
    require(result["cumulative_active_seconds"] < 600, "thread cumulative active ceiling exhausted")
    (output / "READER_JOIN.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result))


if __name__ == "__main__":
    main(sys.argv[1])
