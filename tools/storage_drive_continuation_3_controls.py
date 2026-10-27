"""Source-bound canonical-runtime integration controls, without provider calls."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import random
import subprocess
import sys
import tempfile
import time
from unittest.mock import patch

from tools import storage_drive_continuation_3 as candidate

codec = candidate.codec
private_json = candidate.recovery.private_json


def rejected(callback):
    try:
        callback()
    except ValueError:
        return
    raise AssertionError("negative integration control accepted")


def fixture(
    stage, name, *, upload_error=False, curl_code=0, corrupt=False, long_id=False
):
    root = stage / name
    root.mkdir()
    work = root / "work"
    work.mkdir()
    source = root / "original.bin"
    data = random.Random(37).randbytes(65_536)
    source.write_bytes(data)
    pin = hashlib.sha256(data).hexdigest()
    objects = [(pin, [["original.bin", *codec.identity(source)]])]
    owner = object.__new__(candidate.Continuation)
    owner.root, owner.work = root, work
    owner.plan = {
        "archive_id": "synthetic-archive",
        "source_sha256": codec.sha(candidate.previous.__file__),
        "maximum_new_drive_bytes": 50_000_000_000,
    }
    owner.amendment = {
        "prior_confirmed_uploaded_bytes": 0,
        "prior_uncertain_upload_reserved_bytes": 0,
        "deadline_unix": time.time() + 30,
    }
    owner.progress = {}
    bodies, calls, fetch_urls = {}, [], []

    def broker():
        request_path = work / "drive-bridge/REQUEST.json"
        if not request_path.exists():
            return
        request = json.loads(request_path.read_bytes())
        response = work / ("drive-bridge/" + request["id"] + ".response.json")
        if response.exists():
            return
        calls.append(request["operation"])
        if request["operation"] == "upload":
            body = Path(request["source_path"]).read_bytes()
            assert len(body) == request["expected_bytes"]
            assert hashlib.sha256(body).hexdigest() == request["expected_sha256"]
            remote_id = "x" * 129 if long_id else "remote-" + str(len(bodies))
            bodies[remote_id] = body
            result = {
                "id": request["id"],
                "status": "error" if upload_error else "ok",
                "file_id": remote_id,
                "bytes": len(body),
                "folder_id": candidate.previous.FOLDER,
                "private_owner_only": True,
            }
        else:
            url = (
                "https://example.invalid/"
                + request["file_id"]
                + "/fresh-"
                + str(len(fetch_urls))
            )
            fetch_urls.append(url)
            result = {"id": request["id"], "status": "ok", "download_url": url}
        private_json(response, result)

    owner.check = broker
    drive = candidate.Drive(owner)
    curl_calls = []

    def curl(argv, **kwargs):
        assert argv[:2] == ["/usr/bin/curl", "--config"] and len(argv) == 3
        config = Path(argv[2])
        assert config.stat().st_mode & 0o777 == 0o600
        text = config.read_text()
        assert "insecure" not in text
        settings = dict(
            line.split(" = ", 1) for line in text.splitlines() if " = " in line
        )
        url = json.loads(settings["url"])
        curl_calls.append(url)
        destination = Path(json.loads(settings["output"]))
        if curl_code and (
            curl_code not in candidate.readback_policy.TRANSIENT_CURL
            or len(curl_calls) == 1
        ):
            destination.write_bytes(b"partial")
            return subprocess.CompletedProcess(
                argv, curl_code, b"", b"synthetic curl error"
            )
        body = bodies[url.split("/")[-2]]
        destination.write_bytes(bytes([body[0] ^ 1]) + body[1:] if corrupt else body)
        return subprocess.CompletedProcess(argv, 0, b"", b"")

    def run(small_chunks=False):
        original_writer = codec.ChunkWriter

        def small(*args):
            return original_writer(*args, chunk_bytes=4096)

        with patch.object(candidate.subprocess, "run", curl):
            if small_chunks:
                with patch.object(codec, "ChunkWriter", small):
                    candidate.previous.Migration.pack(owner, drive, 12, objects)
            else:
                candidate.previous.Migration.pack(owner, drive, 12, objects)

    return root, work, source, pin, calls, fetch_urls, curl_calls, run


def controls(stage, root, draft):
    names = []
    _, work, source, pin, calls, _, _, run = fixture(stage, "unwind", upload_error=True)
    rejected(lambda: run(True))
    assert calls == ["upload"]
    assert source.exists() and codec.sha(source) == pin
    assert len(list(work.glob("DRIVE_UPLOAD_3-*.json"))) == 1
    assert (work / "drive-bridge/REQUEST.json").exists()
    assert not list(work.glob("*VERIFIED.json"))
    names.append(
        "canonical-full-pack-gzip-unwind-performs-one-transfer-and-keeps-original"
    )

    _, work, source, _, calls, _, _, run = fixture(stage, "accepted")
    run()
    receipt = json.loads((work / "DRIVE_PACK-00012-VERIFIED.json").read_bytes())
    assert receipt["eviction_complete"] and not source.exists()
    assert receipt["result"]["raw_bytes"] == 65_536
    assert calls.count("upload") == 2 and calls.count("fetch") == 2
    assert len((work / "DRIVE_RESTORE_CATALOG.jsonl").read_text().splitlines()) == 1
    names.append(
        "actual-new-adapter-reconstructs-complete-synthetic-pack-before-unlink"
    )

    _, work, source, pin, _, _, curl_calls, run = fixture(
        stage, "corrupt", corrupt=True
    )
    rejected(run)
    assert len(curl_calls) == 1 and source.exists() and codec.sha(source) == pin
    assert not list(work.glob("*VERIFIED.json"))
    names.append("raw-corruption-is-fatal-with-no-retry-or-eviction")

    _, work, source, _, _, urls, curls, run = fixture(stage, "transient", curl_code=56)
    run()
    assert len(urls) == len(curls) == 3 and len(set(urls)) == 3
    assert not source.exists()
    diagnostics = list(work.glob("DRIVE_READBACK_3-*.json"))
    assert len(diagnostics) == 1
    assert json.loads(diagnostics[0].read_bytes())["curl_exit"] == 56
    names.append(
        "transient-curl-error-uses-fresh-reference-within-existing-attempt-policy"
    )

    _, work, source, pin, _, _, curls, run = fixture(stage, "permanent", curl_code=22)
    rejected(run)
    assert len(curls) == 1 and source.exists() and codec.sha(source) == pin
    assert not list(work.glob("*VERIFIED.json"))
    names.append("permanent-curl-error-is-not-retried")

    _, work, source, _, calls, _, _, run = fixture(stage, "id-bound", long_id=True)
    rejected(run)
    assert source.exists() and calls == ["upload"]
    assert (
        json.loads(next(work.glob("DRIVE_UPLOAD_3-*.json")).read_bytes())["outcome"]
        == "unknown"
    )
    names.append("manifest-id-growth-bound-is-enforced-before-catalog-acceptance")

    owner = object.__new__(candidate.Continuation)
    owner.root, owner.work = root, stage
    owner.amendment = {"deadline_unix": time.time() + 30}
    owner.plan = {
        "minimum_free_bytes": 10_000_000_000,
        "maximum_additional_local_staging_and_catalog_bytes": 384_000_000,
    }
    owner.last_work_measurement = None
    owner.work_bytes = 0
    disk = type("Disk", (), {"free": 100_000_000_000, "used": 300_000_000_000})()
    with (
        patch.object(candidate.shutil, "disk_usage", lambda _: disk),
        patch.object(candidate, "footprint", lambda _: {"charged_bytes": 350_000_000}),
    ):
        rejected(owner.check)
    owner.amendment["deadline_unix"] = time.time() - 1
    rejected(owner.check)
    names.append("actual-owner-rejects-staging-headroom-and-expired-wall")

    candidate.admit(root, draft, require_preflight=False)
    rejected(lambda: candidate.admit(root, draft, require_preflight=True))
    assert not (
        root / candidate.previous.WORK / "DRIVE_CONTINUATION_USAGE_3.json"
    ).exists()
    names.append("actual-source-input-admission-passes-but-draft-cannot-start-owner")

    old = (root / "tools/drive_controller_continuation.js").read_text()
    new = (root / "tools/drive_controller_continuation_3.js").read_text()
    assert new == old.replace(
        "DRIVE_CONTINUATION_USAGE_2.json", "DRIVE_CONTINUATION_USAGE_3.json"
    )
    names.append("controller-keeps-unchanged-bounds-and-protocol-with-new-ledger-only")
    return names


def main(scope_path):
    scope_path = scope_path.resolve()
    work, root = scope_path.parent, scope_path.parents[2]
    scope = json.loads(scope_path.read_bytes())
    assert scope["maximum_invocations"] == 1 and scope["maximum_provider_calls"] == 0
    assert (
        sys.executable == scope["python_executable"]
        and sys.version == scope["python_version"]
    )
    assert time.time() < scope["deadline_unix"] <= 1793150297.974828
    draft = json.loads((work / scope["draft_file"]).read_bytes())
    assert codec.sha(work / scope["draft_file"]) == scope["draft_sha256"]
    for name, pin in scope["source_pins"].items():
        assert codec.sha(root / name) == pin
    for name, pin in scope["protected_files"].items():
        assert codec.sha(work / name) == pin
    ledger = work / codec.relative(scope["usage_file"])
    private_json(ledger, {"closed": False, "invocations_started": 1})
    started = time.time()
    result = {
        "passed": False,
        "provider_calls": 0,
        "owner_starts": 0,
        "source_pins": scope["source_pins"],
        "protected_files": scope["protected_files"],
        "selected_packs": draft["selected_packs"],
        "python_executable": sys.executable,
        "python_version": sys.version,
    }
    try:
        with tempfile.TemporaryDirectory(
            prefix="integration-controls-3-", dir=work
        ) as stage:
            result["controls"] = controls(Path(stage), root, draft)
        for name, pin in scope["protected_files"].items():
            assert codec.sha(work / name) == pin
        assert time.time() < scope["deadline_unix"]
        result.update(passed=True, controls_passed=len(result["controls"]))
    except BaseException as error:
        result.update(error_type=type(error).__name__, error=str(error))
        raise
    finally:
        result.update(seconds=time.time() - started, ended_unix=time.time())
        private_json(work / codec.relative(scope["result_file"]), result)
        private_json(
            ledger,
            {"closed": True, "invocations_started": 1, "seconds": result["seconds"]},
            replace=True,
        )
        print(
            json.dumps(
                {
                    key: value
                    for key, value in result.items()
                    if key not in ("source_pins", "protected_files")
                },
                sort_keys=True,
            )
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--scope", type=Path, required=True)
    main(parser.parse_args().scope)
