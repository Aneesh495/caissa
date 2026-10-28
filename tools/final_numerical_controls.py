"""Focused controls for numerical native descriptors and the real Torch loader."""

import json
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.final_draw_runtime import load_scope, specification
from tools.final_numerical_runtime import NativeFiles, NumericalQuota, install_native_boundary, prepay_native_files
from tools.host_lease import HostLease
from tools.parallel_storage_quota import StorageLimit


def main(path):
    path = Path(path).resolve()
    scope = load_scope(path)
    assert scope["fixture_mode"] and scope["native_actors"] == 0
    with (path.parent / "STARTED.json").open("x") as stream:
        json.dump({"started_unix": time.time()}, stream)
    start = time.monotonic()
    output = Path(scope["output"])
    output.mkdir()
    lease = HostLease(ROOT / "runs")
    quota = NumericalQuota(specification(scope, path))
    quota.create()
    checks, processes, original = [], [], None
    def reject(name, action):
        try:
            action()
        except (StorageLimit, ValueError):
            checks.append(name)
        else:
            raise AssertionError("unsafe numerical operation admitted: " + name)
    quota.install()
    try:
        (output / "producer").mkdir()
        (output / "independent").mkdir()
        (output / "producer/POSITIONS.fen").write_text("synthetic position\n")
        assert quota.read()["data_used"] > 0
        checks.append("actual_numerical_writer_reserved_before_growth")
        reject("committed_numerical_input_immutable", lambda: (output / "producer/POSITIONS.fen").open("ab"))
        reject("escaped_directory_rejected", lambda: (output.parent / "escape").mkdir())
        child = subprocess.run([str(ROOT / ".venv/bin/python"), "-B", "-P", str(ROOT / "tools/final_numerical_runtime.py"), "--scope", str(path), "--stage", "fixture-import"], cwd=ROOT, env=lease.environment(), pass_fds=(lease.stream.fileno(),), capture_output=True, timeout=45)
        if child.returncode or child.stderr:
            raise ValueError("numerical import fixture failed: " + child.stderr.decode(errors="replace")[-1800:])
        loaded = json.loads((output / "fixture.json").read_text())
        assert loaded["checkpoint_model_parameters"] == 8 and loaded["inference"] is False
        checks.append("actual_torch_numpy_checkpoint_import_under_inherited_lease_and_quota")
        factory = NativeFiles(quota)
        with factory.temporary() as stdout, factory.temporary() as stderr:
            reject("unknown_native_descriptor_rejected", lambda: prepay_native_files(quota, stderr, stdout))
            prepay_native_files(quota, stdout, stderr)
            before = quota.read()["data_used"]
            processes, original = install_native_boundary(scope, quota, "fixture")
            process = subprocess.Popen(scope["fixture_commands"]["descriptor"], stdout=stdout, stderr=stderr)
            assert process.wait(timeout=5) == 0 and quota.read()["data_used"] == before
            stdout.seek(0)
            assert stdout.read() == b"native fixture\n"
            checks.append("native_direct_descriptor_write_fully_prepaid_and_contained")
        process = subprocess.Popen(scope["fixture_commands"]["pipe"], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        out, err = process.communicate(input=b"", timeout=5)
        assert process.returncode == 0 and not out and not err
        checks.append("actual_numerical_pipe_native_boundary")
        reject("unknown_native_command_rejected", lambda: subprocess.Popen(["unknown-image"]))
        reject("third_temporary_file_rejected", factory.temporary)
        reject("duplicate_native_start_rejected", lambda: subprocess.Popen(scope["fixture_commands"]["pipe"], stdin=subprocess.PIPE, stdout=subprocess.PIPE))
        assert quota.read()["native_starts"] == 2
    finally:
        if original is not None:
            subprocess.Popen = original
        for process in processes:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=3)
        quota.uninstall()
        quota.update(lambda state: state.update(closed=True))
        lease.close()
    reject("closed_numerical_ledger_rejected", lambda: quota.reserve("data", "producer/probes.jsonl", 1))
    result = {"status": "passed", "controls": checks, "elapsed_seconds": time.monotonic() - start, "native_chess_actors": 0, "synthetic_python_children": 3, "match_games": 0, "inference": False, "full_acceptance": False}
    (path.parent / "RESULT.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({"status": "passed", "controls": len(checks), "seconds": result["elapsed_seconds"]}))


if __name__ == "__main__":
    main(sys.argv[1])
