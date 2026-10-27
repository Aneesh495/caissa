"""One source-bound offline check of the new Drive recovery pieces."""

import argparse
import gzip
import hashlib
import json
import os
from pathlib import Path
import random
import tempfile
import time
from unittest.mock import patch

from tools import storage_drive_recovery as recovery


def require_raises(callback, error=ValueError):
    try:
        callback()
    except error:
        return
    raise AssertionError("negative control was accepted")


def prefix_row(data):
    return {
        "bytes": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
        "git_blob": recovery.codec.blob_oid(data),
        "drive_file_id": "existing-private-id",
    }


def controls(stage):
    passed = []

    def done(name):
        passed.append(name)

    calls = []

    def fail_upload(data):
        calls.append(len(data))
        raise ValueError("synthetic transport failure")

    latch = recovery.FailedUploadLatch(fail_upload)
    adapter = type("Adapter", (), {"put_blob": staticmethod(latch)})()
    sink = recovery.codec.ChunkWriter(adapter, 1_000_000, lambda *_: None, 4096)

    def compress():
        with gzip.GzipFile(fileobj=sink, mode="wb", compresslevel=3, mtime=0) as out:
            out.write(random.Random(7).randbytes(65_536))

    require_raises(compress)
    require_raises(lambda: latch(b"another attempt"))
    assert len(calls) == 1 and latch.failed and sink.rows == []
    done("real-gzip-finalization-cannot-repeat-failed-transfer")

    row = prefix_row(b"prefix")
    objects = {}
    prefix = recovery.ExactPrefix("saved-pack", [row])
    assert (
        prefix.take(b"prefix", "saved-pack-part-00000.bin", objects) == row["git_blob"]
    )
    assert objects[row["git_blob"]] == row
    assert prefix.take(b"new suffix", "saved-pack-part-00001.bin", objects) is None
    done("exact-partial-prefix-reuse-allows-later-new-suffix")

    prefix = recovery.ExactPrefix("saved-pack", [row])
    objects = {}
    require_raises(
        lambda: prefix.take(b"changed", "saved-pack-part-00000.bin", objects)
    )
    assert prefix.position == 0 and objects == {}
    done("corrupt-recompressed-prefix-does-not-advance")
    require_raises(lambda: prefix.take(b"prefix", "saved-pack-part-00001.bin", objects))
    assert prefix.position == 0
    require_raises(lambda: recovery.ExactPrefix("../escape", [row]))
    require_raises(lambda: recovery.ExactPrefix("saved-pack", [{**row, "bytes": True}]))
    done("prefix-order-name-and-row-shape-rejected")

    def fixture(name, answer=None, check_error=None):
        work = stage / name
        work.mkdir()
        (work / "drive-bridge").mkdir(mode=0o700)
        checks = []

        def check():
            checks.append(1)
            if check_error:
                raise check_error
            request = work / "drive-bridge/REQUEST.json"
            value = json.loads(request.read_bytes())
            response = work / ("drive-bridge/" + value["id"] + ".response.json")
            if not response.exists():
                result = answer(value) if callable(answer) else answer
                recovery.private_json(response, {"id": value["id"], **(result or {})})

        bridge = recovery.GuardedBridge(work, check)
        arguments = {
            "source_path": str(work / "drive-spool/upload.bin"),
            "folder_id": recovery.previous.FOLDER,
            "file_name": "synthetic-part.bin",
            "expected_bytes": 6,
            "expected_sha256": hashlib.sha256(b"prefix").hexdigest(),
        }
        return work, bridge, arguments, checks

    accepted = {
        "status": "ok",
        "file_id": "accepted-id",
        "bytes": 6,
        "folder_id": recovery.previous.FOLDER,
        "private_owner_only": True,
    }
    work, bridge, args, _ = fixture("accepted", accepted)
    old_unlink = Path.unlink
    removals = []

    def observed_unlink(path, *args, **kwargs):
        if path.parent.name == "drive-bridge":
            journal = work / "DRIVE_UPLOAD_3-0000001.json"
            recorded = json.loads(journal.read_bytes())
            assert recorded["outcome"] == "metadata-accepted"
            assert recorded["drive_file_id"] == "accepted-id"
            assert journal.stat().st_mode & 0o777 == 0o600
            removals.append(path.name)
        return old_unlink(path, *args, **kwargs)

    with patch.object(Path, "unlink", observed_unlink):
        assert bridge.call("upload", **args)["file_id"] == "accepted-id"
    assert len(removals) == 2
    done("private-durable-upload-id-precedes-response-consumption")

    work, bridge, args, checks = fixture("transport-error", {"status": "error"})
    require_raises(lambda: bridge.call("upload", **args))
    before = len(checks)
    require_raises(lambda: bridge.call("upload", **args))
    assert len(checks) == before == 1
    assert (
        json.loads((work / "DRIVE_UPLOAD_3-0000001.json").read_bytes())["outcome"]
        == "unknown"
    )
    assert (work / "drive-bridge/REQUEST.json").exists()
    assert (work / "drive-bridge/0000001.response.json").exists()
    done("connector-failure-latched-with-original-request-retained")

    work, bridge, args, _ = fixture(
        "privacy", {**accepted, "private_owner_only": False}
    )
    require_raises(lambda: bridge.call("upload", **args))
    assert (
        json.loads((work / "DRIVE_UPLOAD_3-0000001.json").read_bytes())["outcome"]
        == "unknown"
    )
    done("metadata-privacy-mismatch-remains-unaccepted")

    work, bridge, args, _ = fixture(
        "deadline", check_error=TimeoutError("synthetic bound")
    )
    require_raises(lambda: bridge.call("upload", **args), TimeoutError)
    assert (
        json.loads((work / "DRIVE_UPLOAD_3-0000001.json").read_bytes())["outcome"]
        == "unknown"
    )
    assert (work / "drive-bridge/REQUEST.json").exists()
    done("deadline-preserves-unresolved-upload-intent")

    work, bridge, args, _ = fixture("identity", {**accepted, "id": "9999999"})
    require_raises(lambda: bridge.call("upload", **args))
    assert (work / "drive-bridge/0000001.response.json").exists()
    done("wrong-response-identity-is-retained-and-rejected")

    synthetic_url = "https://example.invalid/synthetic-private-reference"
    work, bridge, _, _ = fixture(
        "fetch", {"status": "ok", "download_url": synthetic_url}
    )
    result = bridge.call("fetch", file_id="existing-id", expected_bytes=6)
    assert result["download_url"] == synthetic_url
    assert not list(work.glob("DRIVE_UPLOAD_3-*"))
    assert list((work / "drive-bridge").iterdir()) == []
    done("fetch-reference-never-enters-durable-upload-journal")

    work, bridge, args, _ = fixture("counter", accepted)
    recovery.private_json(
        work / "drive-bridge/0000991.controller.json", {"status": "error"}
    )
    bridge = recovery.GuardedBridge(work, bridge.check)
    bridge.call("upload", **args)
    assert (work / "DRIVE_UPLOAD_3-0000992.json").exists()
    recovery.private_json(work / "drive-bridge/REQUEST.json", {"id": "0000993"})
    require_raises(lambda: recovery.GuardedBridge(work, bridge.check))
    done("counter-survives-manual-reconciliation-and-pending-request-blocks-start")

    work, bridge, args, checks = fixture("unsafe-path", accepted)
    require_raises(
        lambda: bridge.call("upload", **{**args, "source_path": "/outside.bin"})
    )
    assert checks == [] and not list(work.glob("DRIVE_UPLOAD_3-*"))
    done("unsafe-source-rejected-before-provider-or-intent")
    return passed


def main(scope_path):
    scope_path = scope_path.resolve()
    scope = json.loads(scope_path.read_bytes())
    root = scope_path.parents[2]
    work = scope_path.parent
    assert scope["kind"] == "single offline storage recovery control invocation"
    assert scope["maximum_invocations"] == 1 and scope["maximum_provider_calls"] == 0
    assert time.time() < scope["deadline_unix"] <= 1793150297.974828
    for relative, pin in scope["source_pins"].items():
        assert hashlib.sha256((root / relative).read_bytes()).hexdigest() == pin
    for relative, pin in scope["preserved_input_pins"].items():
        assert hashlib.sha256((root / relative).read_bytes()).hexdigest() == pin
    ledger = work / "DRIVE_RECOVERY_CONTROLS_3_USAGE.json"
    recovery.private_json(ledger, {"closed": False, "invocations_started": 1})
    started = time.time()
    result = {"passed": False, "provider_calls": 0, "owner_starts": 0}
    try:
        with tempfile.TemporaryDirectory(
            prefix="recovery-controls-3-", dir=work
        ) as stage:
            result["controls"] = controls(Path(stage))
        for relative, pin in scope["preserved_input_pins"].items():
            assert hashlib.sha256((root / relative).read_bytes()).hexdigest() == pin
        assert time.time() < scope["deadline_unix"]
        result.update(passed=True, controls_passed=len(result["controls"]))
    except BaseException as error:
        result.update(error_type=type(error).__name__, error=str(error))
        raise
    finally:
        result.update(seconds=time.time() - started, ended_unix=time.time())
        recovery.private_json(work / "DRIVE_RECOVERY_CONTROLS_3_RESULT.json", result)
        recovery.private_json(
            ledger,
            {"closed": True, "invocations_started": 1, "seconds": result["seconds"]},
            replace=True,
        )
        print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--scope", type=Path, required=True)
    main(parser.parse_args().scope)
