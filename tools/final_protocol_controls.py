"""New protocol writer/descriptor/bootstrap controls, without a chess actor."""

import json
import os
from pathlib import Path
import resource
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.final_protocol_runtime import ProtocolQuota, reserve_native_stderr
from tools.final_draw_runtime import load_scope, specification
from tools.host_lease import HostLease
from tools.parallel_storage_quota import StorageLimit


def main(path):
    path = Path(path).resolve()
    scope = load_scope(path)
    assert scope["fixture_mode"] and scope["native_actors"] == 0
    with (path.parent / "STARTED.json").open("x") as stream:
        json.dump({"started_unix": time.time()}, stream)
    started = time.monotonic()
    output = Path(scope["output"])
    output.mkdir()
    (output / "producer").mkdir()
    lease = HostLease(ROOT / "runs")
    quota = ProtocolQuota(specification(scope, path))
    quota.create()
    checks = []
    def reject(name, action):
        try:
            action()
        except (StorageLimit, ValueError):
            checks.append(name)
        else:
            raise AssertionError("unsafe protocol operation admitted: " + name)
    quota.install()
    try:
        with (output / "producer/transcript.jsonl").open("xb") as stream:
            stream.write(b'{"send":"synthetic","ns":1}\n')
        checks.append("actual_protocol_writer_reserved_before_growth")
        reject("draw_namespace_not_reused", lambda: (output / "independent/native-replay.jsonl").write_text("x"))
        reject("escaped_protocol_write_rejected", lambda: (output.parent / "escape").write_text("x"))
        from tools.campaign_process import atomic
        atomic(output / "PROTOCOL_REPLAY.json", {"status": "synthetic"})
        checks.append("actual_protocol_reader_result_writer")
        with (output / "producer/stderr.log").open("wb") as stderr:
            reserve_native_stderr(quota, stderr, 65536)
            before = quota.read()["control_used"]
            def limit():
                resource.setrlimit(resource.RLIMIT_FSIZE, (65536, 65536))
            actor = subprocess.run([str(ROOT / ".venv/bin/python"), "-B", "-P", "-c", "import os;os.write(2,b'fixture-stderr'*100)"], stdout=subprocess.PIPE, stderr=stderr, timeout=5, preexec_fn=limit)
            assert actor.returncode == 0 and quota.read()["control_used"] == before
        assert (output / "producer/stderr.log").stat().st_size < 65536
        checks.append("native_style_descriptor_reserved_before_direct_write")
        child = subprocess.run([str(ROOT / ".venv/bin/python"), "-B", "-P", str(ROOT / "tools/final_protocol_runtime.py"), "--scope", str(path), "--stage", "fixture"], cwd=ROOT, env=lease.environment(), pass_fds=(lease.stream.fileno(),), capture_output=True, timeout=10)
        assert child.returncode == 0 and not child.stderr and (output / "fixture.txt").read_text() == "protocol inherited bootstrap\n"
        checks.append("actual_protocol_child_inherited_lease_and_quota")
        with (output / "fixture.txt").open("wb") as other:
            reject("unknown_native_descriptor_rejected", lambda: reserve_native_stderr(quota, other, 65536))
        with (output / "producer/stderr.log").open("ab") as stderr:
            reject("insufficient_native_descriptor_reservation_rejects_before_launch", lambda: reserve_native_stderr(quota, stderr, 3000000))
        assert quota.read().get("failure")
    finally:
        quota.uninstall()
        quota.update(lambda state: state.update(closed=True))
        lease.close()
    assert len(checks) == 8
    result = {"status": "passed", "controls": checks, "elapsed_seconds": time.monotonic() - started, "native_actors": 0, "match_games": 0, "synthetic_python_children": 2, "full_gate": False, "full_acceptance": False}
    (path.parent / "RESULT.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({"status": "passed", "controls": len(checks), "elapsed_seconds": result["elapsed_seconds"], "native_actors": 0, "match_games": 0}))


if __name__ == "__main__":
    main(sys.argv[1])
