"""Focused lossless journal transport controls without native chess execution."""

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.final_draw_runtime import load_scope, specification
from tools.final_restoration_runtime import RestorationQuota
from tools.host_lease import HostLease
from tools.parallel_storage_quota import StorageLimit
from tools.restoration_journal import open_journal


def main(path):
    path = Path(path).resolve()
    scope = load_scope(path)
    assert scope["fixture_mode"] and scope["native_actors"] == 0
    with (path.parent / "STARTED.json").open("x") as stream:
        json.dump({"started_unix": time.time()}, stream)
    start = time.monotonic()
    output = Path(scope["output"])
    output.mkdir()
    (output / "producer").mkdir()
    (output / "independent").mkdir()
    lease = HostLease(ROOT / "runs")
    quota = RestorationQuota(specification(scope, path))
    quota.create()
    checks = []
    def reject(name, action):
        try:
            action()
        except (ValueError, OSError, EOFError):
            checks.append(name)
        else:
            raise AssertionError("invalid restoration transport admitted: " + name)
    def decode(p, ceiling=1000000):
        rows = []
        with open_journal(p, "rb", compressed=True, maximum_bytes=ceiling) as stream:
            before = os.fstat(stream.fileno())
            while row := stream.readline(128 * 1024 + 1):
                rows.append(row)
            assert stream.tell() == sum(map(len, rows))
            assert before.st_size == os.fstat(stream.fileno()).st_size
        return b"".join(rows)
    quota.install()
    try:
        payload = (b'{"state":[1,2,3],"reply_sha256":"fixed fixture"}\n') * 1000
        p = output / "roundtrip.gz"
        with open_journal(p, "xb", compressed=True, maximum_bytes=len(payload)) as stream:
            for row in payload.splitlines(keepends=True):
                stream.write(row)
            stream.flush()
            assert stream.tell() == len(payload)
        assert decode(p) == payload and p.stat().st_size < len(payload)
        checks.append("compressed_roundtrip_preserves_every_logical_byte_and_count")
        assert hashlib.sha256(decode(p)).digest() == hashlib.sha256(payload).digest()
        checks.append("original_uncompressed_digest_contract_preserved")
        raw = bytearray(p.read_bytes());raw[-8] ^= 1
        (output / "corrupt.gz").write_bytes(raw)
        reject("corrupt_gzip_crc_rejected", lambda: decode(output / "corrupt.gz"))
        (output / "truncated.gz").write_bytes(p.read_bytes()[:-8])
        reject("truncated_gzip_trailer_rejected", lambda: decode(output / "truncated.gz"))
        reject("decoded_logical_ceiling_enforced", lambda: decode(p, len(payload)-1))
        with open_journal(output / "plain.jsonl", "xb", maximum_bytes=len(payload)) as stream:
            stream.write(payload)
        assert (output / "plain.jsonl").read_bytes() == payload
        checks.append("plain_journal_bytes_remain_unchanged")
        reject("committed_compressed_journal_rewrite_rejected", lambda: p.open("ab"))
        reject("escaped_compressed_journal_write_rejected", lambda: (output.parent / "escape.gz").write_bytes(b"x"))
        child = subprocess.run([str(ROOT / ".venv/bin/python"), "-B", "-P", str(ROOT / "tools/final_restoration_runtime.py"), "--scope", str(path), "--stage", "fixture"], cwd=ROOT, env=lease.environment(), pass_fds=(lease.stream.fileno(),), capture_output=True, timeout=10)
        assert child.returncode == 0 and not child.stderr and decode(output / "producer/observations.jsonl.gz") == b"inherited restoration journal\n"
        checks.append("actual_child_compressor_inherits_lease_and_quota")
        with open_journal(output / "independent/native-replay.jsonl.gz", "xb", compressed=True, maximum_bytes=1) as stream:
            reject("logical_writer_growth_rejected_before_compression", lambda: stream.write(b"too large"))
    finally:
        quota.uninstall()
        quota.update(lambda state: state.update(closed=True))
        lease.close()
    reject("closed_restoration_ledger_rejected", lambda: quota.reserve("data", "roundtrip.gz", 1))
    result = {"status": "passed", "controls": checks, "elapsed_seconds": time.monotonic()-start, "native_actors": 0, "match_games": 0, "synthetic_python_children": 1, "full_acceptance": False}
    (path.parent / "RESULT.json").write_text(json.dumps(result, indent=2)+"\n")
    print(json.dumps({"status": "passed", "controls": len(checks), "elapsed_seconds": result["elapsed_seconds"]}))


if __name__ == "__main__":
    main(sys.argv[1])
