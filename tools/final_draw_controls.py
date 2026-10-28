"""One new synthetic check of final-draw wiring, with no chess actor starts."""

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.final_draw_runtime import DrawQuota, close_probe, copy_file, load_scope, specification
from tools.parallel_storage_quota import StorageLimit
from tools.host_lease import HostLease


def main(scope_path):
    scope_path = Path(scope_path).resolve()
    scope = load_scope(scope_path)
    assert scope["fixture_mode"] and scope["native_actors"] == 0
    assert not (scope_path.parent / "STARTED.json").exists()
    (scope_path.parent / "STARTED.json").write_text(json.dumps({"unix": time.time()}) + "\n")
    started = time.monotonic()
    output = Path(scope["output"])
    output.mkdir()
    (output / "producer").mkdir()
    (output / "independent").mkdir()
    source = scope_path.parent / "synthetic-input.bin"
    source.write_bytes(b"fixture-" * 25000)
    lease = HostLease(ROOT / "runs")
    quota = DrawQuota(specification(scope, scope_path))
    quota.create()
    checks = []
    def rejected(name, action):
        try:
            action()
        except (StorageLimit, ValueError):
            checks.append(name)
        else:
            raise AssertionError("unsafe operation admitted: " + name)
    quota.install()
    try:
        with (output / "producer/observations.jsonl").open("xb") as stream:
            stream.write(b"actual reserved output\n")
        checks.append("actual_writer_reserved_before_growth")
        from tools.campaign_process import atomic
        atomic(output / "producer/PROGRESS.json", {"observations": 1})
        first = quota.read()["control_used"]
        atomic(output / "producer/PROGRESS.json", {"observations": 2})
        assert quota.read()["control_used"] == first
        checks.append("actual_atomic_progress_peak_accounted")
        copied = output / "independent/selected.cai"
        copy_file(source, copied)
        assert hashlib.sha256(copied.read_bytes()).digest() == hashlib.sha256(source.read_bytes()).digest()
        checks.append("real_reader_copy_uses_metered_streams")
        escaped = output.parent / "escape.bin"
        rejected("escaped_write_rejected_before_creation", lambda: escaped.write_bytes(b"x"))
        assert not escaped.exists()
        rejected("unknown_output_rejected", lambda: (output / "SCOPE.json").write_text("x"))
        rejected("raw_open_bypass_rejected", lambda: os.open(output / "fixture.txt", os.O_CREAT | os.O_WRONLY))
        with (output / "fixture.txt").open("wb") as stream:
            rejected("raw_regular_descriptor_write_rejected", lambda: os.write(stream.fileno(), b"x"))
        (output / "fixture.txt").unlink()
        (output / "fixture.txt").symlink_to(source)
        rejected("linked_destination_rejected", lambda: (output / "fixture.txt").write_text("x"))
        (output / "fixture.txt").unlink()
        child = subprocess.run([str(ROOT / ".venv/bin/python"), "-B", "-P", str(ROOT / "tools/final_draw_runtime.py"), "--scope", str(scope_path), "--stage", "fixture"], cwd=ROOT, env=lease.environment(), pass_fds=(lease.stream.fileno(),), capture_output=True, timeout=10)
        assert child.returncode == 0 and not child.stderr and (output / "fixture.txt").read_text() == "actual inherited bootstrap\n"
        checks.append("actual_child_bootstrap_inherited_lease_and_quota")
        process = subprocess.Popen([str(ROOT / ".venv/bin/python"), "-B", "-P", "-c", "import time;time.sleep(20)"], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=False)
        assert os.getpgid(process.pid) == os.getpgrp()
        probe = SimpleNamespace(process=process, reader=SimpleNamespace(close=lambda: None), writer=SimpleNamespace(close=lambda: None))
        close_probe(probe)
        assert process.poll() is not None
        checks.append("actual_contained_child_termination_and_reap")
        with (output / "fixture.txt").open("wb") as stream:
            rejected("quota_exhaustion_prevents_growth", lambda: stream.write(b"x" * 3000000))
        assert (output / "fixture.txt").stat().st_size == 0 and quota.read().get("failure")
    finally:
        quota.uninstall()
        quota.update(lambda state: state.update(closed=True))
        lease.close()
    rejected("closed_ledger_cannot_be_reused", lambda: quota.reserve("control", "fixture.txt", 1))
    assert len(checks) == 12
    result = {"status": "passed", "controls": checks, "elapsed_seconds": time.monotonic() - started, "native_actors": 0, "games": 0, "synthetic_python_children": 2, "full_gate": False, "full_acceptance": False}
    (scope_path.parent / "RESULT.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({"status": "passed", "controls": len(checks), "elapsed_seconds": result["elapsed_seconds"], "native_actors": 0, "games": 0}))


if __name__ == "__main__":
    main(sys.argv[1])
