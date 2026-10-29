"""Focused new regression checks for the observed model-before-enable failure."""

import json
import os
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.final_draw_runtime import load_scope
from tools.thread_probe import Native
from verification.thread_runtime import inspect_events


def main(path):
    scope = load_scope(path)
    assert scope["native_actors"] == 0 and not (path.parent / "STARTED.json").exists()
    (path.parent / "STARTED.json").write_text(json.dumps({"unix": time.time()}) + "\n")
    start = time.monotonic()
    profile = json.loads(Path(scope["profile"]).read_text())
    checks, first_commands = [], None
    for threads in [1, 2, 4, 8]:
        client = Native.__new__(Native)
        commands = []
        client.scope, client.threads = {"network": "synthetic/selected.cai"}, threads
        client.send, client.until = commands.append, lambda *_: []
        client.setup(profile["options"])
        assert commands.index("setoption name EvalFile value synthetic/selected.cai") < commands.index("setoption name Use Neural value true")
        assert "setoption name Threads value " + str(threads) in commands
        if threads == 1:
            first_commands = commands
    checks.append("actual_producer_loads_model_before_enable_all_thread_modes")
    expected = {"release_engine_sha256": profile["release_engine_sha256"], "instrumented_engine_sha256": profile["instrumented_engine_sha256"], "network_sha256": profile["network_sha256"], "runtime_sha256": profile["instrumented_runtime_sha256"], "network_path": "synthetic/selected.cai", "runtime_path": "synthetic/runtime.dylib"}
    rows = [{"event": "open", "session": 0, "kind": "release", "threads": 1, "engine_sha256": expected["release_engine_sha256"], "runtime_sha256": None, "network_sha256": expected["network_sha256"]}]
    stamp = 0
    for text in first_commands:
        stamp += 1
        rows.append({"event": "send", "session": 0, "ns": stamp, "text": text})
        if text in ["uci", "isready"]:
            stamp += 1
            rows.append({"event": "recv", "session": 0, "ns": stamp, "text": "uciok" if text == "uci" else "readyok"})
    try:
        inspect_events(iter(rows), profile, expected)
    except ValueError as e:
        assert str(e) == "incomplete full thread runtime evidence"
    else:
        raise AssertionError("prefix passed full endpoint")
    checks.append("reader_accepts_correct_setup_prefix_but_not_incomplete_sample")
    bad = list(rows)
    i = next(i for i, x in enumerate(bad) if x.get("text", "").startswith("setoption name EvalFile"))
    bad[i] = {**bad[i], "text": "setoption name Use Neural value true"}
    try:
        inspect_events(iter(bad), profile, expected)
    except ValueError as e:
        assert str(e) == "applied option/setup command differs"
    else:
        raise AssertionError("premature neural enable accepted")
    checks.append("reader_rejects_neural_enable_before_model_load")
    read_fd, write_fd = os.pipe()
    stream = os.fdopen(read_fd, "rb", buffering=0)
    captured = []
    class Log:
        def emit(self, event, session, **fields):
            captured.append({"event": event, **fields})
    client = Native.__new__(Native)
    client.streams, client.buffer, client.journal, client.index, client.ready = {stream: "stdout"}, {"stdout": bytearray()}, Log(), 0, []
    try:
        os.write(write_fd, b"info string error load EvalFile before enabling neural evaluation\n")
        try:
            client.pump(0)
        except ValueError as e:
            assert str(e).startswith("native rejected applied setup/search")
        else:
            raise AssertionError("native error not fatal immediately")
        assert len(captured) == 1 and captured[0]["text"].startswith("info string error")
    finally:
        os.close(write_fd)
        stream.close()
    checks.append("actual_owned_pipe_fails_fast_and_retains_native_error")
    result = {"status": "passed", "controls": checks, "elapsed_seconds": time.monotonic()-start, "native_chess_actors": 0, "synthetic_python_children": 0, "games": 0, "original_18_controls_reexecuted": False, "full_acceptance": False}
    (path.parent / "RESULT.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({"status": "passed", "controls": len(checks), "elapsed_seconds": result["elapsed_seconds"], "native_chess_actors": 0}))


if __name__ == "__main__":
    main(Path(sys.argv[1]).resolve())
