"""New rules journal, native-containment and child-wiring controls, no chess."""

import hashlib
import json
import os
from pathlib import Path
import resource
import subprocess
import sys
import time
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.final_draw_runtime import copy_file, load_scope, specification
from tools.final_rules_runtime import JOURNAL_LIMIT, RulesQuota, close_rules_probe, install_native_boundary
from tools.host_lease import HostLease
from tools.parallel_storage_quota import StorageLimit


def main(path):
    path = Path(path).resolve()
    scope = load_scope(path)
    assert scope["fixture_mode"] and scope["native_actors"] == 0
    resource.setrlimit(resource.RLIMIT_FSIZE, (scope["fixture_file_limit_bytes"], JOURNAL_LIMIT))
    with (path.parent / "STARTED.json").open("x") as stream:
        json.dump({"started_unix": time.time()}, stream)
    started = time.monotonic()
    output = Path(scope["output"])
    output.mkdir()
    (output / "producer").mkdir()
    source = path.parent / "synthetic-input.bin"
    source.write_bytes(b"rules-fixture-" * 10000)
    lease = HostLease(ROOT / "runs")
    quota = RulesQuota(specification(scope, path))
    quota.create()
    checks = []
    def reject(name, action):
        try:
            action()
        except (StorageLimit, ValueError):
            checks.append(name)
        else:
            raise AssertionError("unsafe rules operation admitted: " + name)
    quota.install()
    original, processes = None, []
    try:
        with (output / "producer/observations.jsonl").open("xb") as stream:
            stream.write(b"a" * (4 * 1024**2 + 65536))
            reject("sparse_journal_seek_rejected", lambda: stream.seek(1, 2))
        assert quota.read()["data_used"] >= (output / "producer/observations.jsonl").stat().st_size > 4 * 1024**2
        checks.append("actual_large_journal_writer_crosses_old_4MiB_limit_with_credits")
        reject("committed_journal_reopen_rejected", lambda: (output / "producer/observations.jsonl").open("ab"))
        reject("escaped_rules_output_rejected", lambda: (output.parent / "escape").write_text("x"))
        reject("draw_namespace_rejected", lambda: (output / "producer/profile.json").write_text("x"))
        with (output / "fixture.txt").open("wb") as stream:
            reject("raw_regular_descriptor_write_rejected", lambda: os.write(stream.fileno(), b"x"))
        (output / "fixture.txt").unlink()
        (output / "fixture.txt").symlink_to(source)
        reject("linked_rules_destination_rejected", lambda: (output / "fixture.txt").write_text("x"))
        (output / "fixture.txt").unlink()
        child = subprocess.run([str(ROOT / ".venv/bin/python"), "-B", "-P", str(ROOT / "tools/final_rules_runtime.py"), "--scope", str(path), "--stage", "fixture"], cwd=ROOT, env=lease.environment(), pass_fds=(lease.stream.fileno(),), capture_output=True, timeout=10)
        assert child.returncode == 0 and not child.stderr and (output / "fixture.txt").read_text() == "rules inherited bootstrap\n"
        checks.append("actual_rules_child_inherited_lease_and_quota")
        from tools.campaign_process import Campaign, atomic
        nested = Campaign(output / "independent", {"synthetic": True}, 10)
        (output / "independent/bin").mkdir()
        copy_file(source, output / "independent/bin/caissa")
        assert hashlib.sha256(source.read_bytes()).digest() == hashlib.sha256((output / "independent/bin/caissa").read_bytes()).digest()
        checks.append("actual_reader_copy_uses_metered_stream")
        atomic(output / "independent/RULES.json", {"status": "synthetic"})
        checks.append("actual_independent_result_atomic_writer")
        processes, original = install_native_boundary(scope, quota, "fixture")
        commands = scope["fixture_commands"]
        reject("unadmitted_native_command_rejected_before_launch", lambda: subprocess.Popen(["unknown-image"], stdout=subprocess.PIPE))
        process = subprocess.Popen(commands["produce-inspect"], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        probe = SimpleNamespace(process=process, stderr=bytearray(), buffer=b"", reader=SimpleNamespace(close=lambda: None), writer=SimpleNamespace(close=lambda: None))
        close_rules_probe(probe)
        assert process.returncode == 0 and os.getpgid(os.getpid()) == os.getpgrp()
        checks.append("actual_contained_probe_closes_with_clean_transport")
        perft = next(k for k in commands if k.startswith("perft-"))
        nested.run(perft, commands[perft], 5, maximum_output_bytes=1024)
        record = json.loads((output / "independent" / (perft + ".json")).read_text())
        assert record["exit"] == 0 and record["reason"] == "completed" and not record["cleanup_warnings"]
        events = [json.loads(line) for line in (output / "independent/COMMANDS.jsonl").read_text().splitlines()]
        event = next(row for row in events if row["event"] == "stage-started")
        assert not event["owns_process_group"] and (output / "independent" / (perft + ".log")).read_text() == "7\n"
        checks.append("actual_nested_perft_campaign_uses_direct_child_containment")
        nested.close("synthetic")
        with (output / "fixture.txt").open("wb") as stream:
            reject("native_regular_output_descriptor_rejected", lambda: subprocess.Popen(commands["blocked-probe"], stdout=stream))
        process = subprocess.Popen(commands["blocked-probe"], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        probe = SimpleNamespace(process=process, stderr=bytearray(), buffer=b"", reader=SimpleNamespace(close=lambda: None), writer=SimpleNamespace(close=lambda: None))
        reject("forced_probe_cleanup_is_failure_and_reaped", lambda: close_rules_probe(probe))
        assert process.poll() is not None
        with (output / "independent/native-observations.jsonl").open("xb") as stream:
            reject("individual_large_journal_limit_before_growth", lambda: stream.write(b"x" * (scope["journal_limit_bytes"] + 1)))
            assert stream.tell() == 0
            reject("shared_data_exhaustion_before_growth", lambda: stream.write(b"x" * (4 * 1024**2)))
            assert stream.tell() == 0 and quota.read().get("failure")
        reject("duplicate_native_start_rejected", lambda: subprocess.Popen(commands["produce-inspect"], stdout=subprocess.PIPE))
        assert quota.read()["native_starts"] == 3 and all(p.poll() is not None for p in processes)
    finally:
        for process in processes:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=3)
        if original is not None:
            from tools.campaign_process import Campaign
            subprocess.Popen, Campaign.run = original
        quota.uninstall()
        quota.update(lambda state: state.update(closed=True))
        lease.close()
    reject("closed_rules_ledger_cannot_be_reused", lambda: quota.reserve("control", "fixture.txt", 1))
    assert len(checks) == 19, checks
    result = {"status": "passed", "controls": checks, "elapsed_seconds": time.monotonic() - started, "native_actors": 0, "match_games": 0, "synthetic_python_children": 4, "full_gate": False, "full_acceptance": False}
    (path.parent / "RESULT.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({"status": "passed", "controls": len(checks), "elapsed_seconds": result["elapsed_seconds"], "native_actors": 0, "match_games": 0}))


if __name__ == "__main__":
    main(sys.argv[1])
