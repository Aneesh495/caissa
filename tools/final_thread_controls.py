"""New thread-reader forgery and actual namespace/bootstrap controls, no engines."""

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

import chess

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.final_draw_runtime import load_scope, specification
from tools.final_thread_runtime import ThreadQuota
from tools.host_lease import HostLease
from tools.parallel_storage_quota import StorageLimit
from tools.thread_probe import Journal
from verification.thread_runtime import inspect_events


def main(path):
    scope = load_scope(path)
    assert scope["fixture_mode"] and scope["native_actors"] == 0
    (path.parent / "STARTED.json").write_text(json.dumps({"unix": time.time()}) + "\n")
    started = time.monotonic()
    profile = json.loads(Path(scope["profile"]).read_text())
    expected = {"release_engine_sha256": profile["release_engine_sha256"], "instrumented_engine_sha256": profile["instrumented_engine_sha256"], "network_sha256": profile["network_sha256"], "runtime_sha256": profile["instrumented_runtime_sha256"], "network_path": "synthetic/selected.cai", "runtime_path": "synthetic/runtime.dylib"}
    rows, stamp = [], 0
    def emit(event, session, **fields):
        nonlocal stamp
        if event in {"send", "recv", "stderr"}:
            stamp += 1_000_000
            fields["ns"] = stamp
        rows.append({"event": event, "session": session, **fields})
    for sid, (kind, threads) in enumerate((k, t) for k in ["release", "instrumented"] for t in [1, 2, 4, 8]):
        emit("open", sid, kind=kind, threads=threads, engine_sha256=expected[kind + "_engine_sha256"], network_sha256=expected["network_sha256"], runtime_sha256=None if kind == "release" else expected["runtime_sha256"])
        emit("send", sid, text="uci")
        emit("recv", sid, text="uciok")
        for key, value in {**profile["options"], "Threads": threads, "EvalFile": expected["network_path"]}.items():
            emit("send", sid, text="setoption name " + key + " value " + (str(value).lower() if type(value) is bool else str(value)))
        emit("send", sid, text="isready")
        emit("recv", sid, text="readyok")
        for i in range(1000 if kind == "release" else 16):
            fen = profile["positions"][i % 4]["fen"]
            best = next(iter(chess.Board(fen).legal_moves)).uci()
            for text in ["ucinewgame", "position fen " + fen, "isready"]:
                emit("send", sid, text=text)
            emit("recv", sid, text="readyok")
            emit("send", sid, text="go infinite" if kind == "release" else "go nodes 2048")
            emit("recv", sid, text="info depth 2 nodes 100 score cp 0 pv " + best)
            if kind == "release":
                emit("send", sid, text="stop")
            emit("recv", sid, text="bestmove " + best)
        emit("send", sid, text="quit")
        stderr = "dyld[1]: " + expected["runtime_path"] + "\n" if kind == "instrumented" else ""
        if stderr:
            emit("stderr", sid, text=stderr[:-1])
        emit("close", sid, native_exit=0, forced_cleanup=False, stderr_bytes=len(stderr.encode()), retained_stderr_bytes=len(stderr.encode()), dropped_optional_bytes=0, stderr_sha256=hashlib.sha256(stderr.encode()).hexdigest(), critical_stderr_bytes=0, runtime_seen=kind == "instrumented")
    result = inspect_events(iter(rows), profile, expected)
    assert result["stop_sequences"] == 4000 and result["instrumented_searches"] == 64 and result["stop_ms"]["p99"] == 1
    checks = ["full_frozen_4000_stop_64_instrumented_synthetic_reader"]
    def reject(name, index, changes):
        changed = list(rows)
        changed[index] = {**rows[index], **changes}
        try:
            inspect_events(iter(changed), profile, expected)
        except ValueError:
            checks.append(name)
        else:
            raise AssertionError("forged thread evidence accepted: " + name)
    locate = lambda prefix: next(i for i, r in enumerate(rows) if r.get("text", "").startswith(prefix))
    reject("wrong_release_actor", 0, {"engine_sha256": "0" * 64})
    reject("wrong_model", 0, {"network_sha256": "0" * 64})
    reject("wrong_applied_hash", locate("setoption name Hash"), {"text": "setoption name Hash value 32"})
    reject("wrong_applied_evaluator", locate("setoption name Use Neural"), {"text": "setoption name Use Neural value false"})
    reject("changed_node_budget", locate("go nodes"), {"text": "go nodes 1024"})
    reject("missing_active_witness", locate("info depth"), {"text": "info depth 1 nodes 100 score cp 0 pv a2a3"})
    reject("early_bestmove", locate("info depth"), {"text": "bestmove a2a3"})
    reject("illegal_PV", locate("info depth"), {"text": "info depth 2 nodes 100 score cp 0 pv a1a8"})
    reject("clock_reversal", locate("stop"), {"ns": 1})
    close = next(i for i, r in enumerate(rows) if r["event"] == "close")
    reject("native_sanitizer_exit", close, {"native_exit": 66})
    reject("forced_native_cleanup", close, {"forced_cleanup": True})
    reject("false_stderr_digest", close, {"stderr_sha256": "0" * 64})
    instrumented = next(i for i, r in enumerate(rows) if r["event"] == "open" and r["kind"] == "instrumented")
    reject("wrong_instrumented_runtime", instrumented, {"runtime_sha256": "0" * 64})
    try:
        inspect_events(iter(rows[:-1]), profile, expected)
    except ValueError:
        checks.append("missing_final_exit")
    else:
        raise AssertionError("missing final exit accepted")
    output = Path(scope["output"])
    output.mkdir()
    (output / "producer").mkdir()
    lease = HostLease(ROOT / "runs")
    quota = ThreadQuota(specification(scope, path))
    quota.create()
    quota.install()
    try:
        journal = Journal(output / "producer/transcript.jsonl", quota)
        credit = quota.read()["data_used"]
        journal.emit("synthetic_writer", 0, value=True)
        journal.close()
        assert quota.read()["data_used"] == credit and credit >= scope["journal_limit_bytes"]
        checks.append("actual_journal_prepaid_before_timing")
        try:
            (output / "producer/transcript.jsonl").open("wb")
        except StorageLimit:
            checks.append("actual_thread_journal_immutable")
        else:
            raise AssertionError("thread journal rewrite accepted")
        child = subprocess.run([str(ROOT / ".venv/bin/python"), "-B", "-P", str(ROOT / "tools/final_thread_runtime.py"), "--scope", str(path), "--stage", "fixture"], cwd=ROOT, env=lease.environment(), pass_fds=(lease.stream.fileno(),), capture_output=True, timeout=10)
        assert child.returncode == 0 and not child.stderr and (output / "fixture.txt").read_text() == "inherited thread quota/lease\n"
        checks.append("actual_thread_child_inherited_namespace_and_lease")
    finally:
        quota.uninstall()
        quota.update(lambda state: state.update(closed=True))
        lease.close()
    assert len(checks) == 18
    final = {"status": "passed", "controls": checks, "elapsed_seconds": time.monotonic() - started, "synthetic_python_children": 1, "native_chess_actors": 0, "games": 0, "full_acceptance": False}
    (path.parent / "RESULT.json").write_text(json.dumps(final, indent=2) + "\n")
    print(json.dumps({"status": "passed", "controls": len(checks), "elapsed_seconds": final["elapsed_seconds"], "native_chess_actors": 0, "games": 0}))


if __name__ == "__main__":
    main(Path(sys.argv[1]).resolve())
