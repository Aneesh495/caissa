"""Actual streaming transport and semantic rejection controls for private storage."""

import hashlib
import io
import json
from pathlib import Path
import tempfile
import time
import tools.storage_archive as storage

from tools.storage_archive import (
    ChunkReader,
    ChunkWriter,
    SCHEMA,
    blob_oid,
    encoded,
    keep_local,
    relative,
    verify_pack,
)
import gzip
import tarfile


class MemoryGithub:
    def __init__(self):
        self.blobs = {}

    def put_blob(self, data):
        oid = blob_oid(data)
        self.blobs[oid] = data
        return oid

    def get_blob(self, oid):
        data = self.blobs[oid]
        if blob_oid(data) != oid:
            raise ValueError("Git object changed")
        return data

    def commit(self, entries, message):
        for row in entries:
            assert row["sha"] in self.blobs
        return "1" * 40


def reject(function):
    try:
        function()
    except (ValueError, OSError, KeyError, EOFError):
        return
    raise AssertionError("changed storage control was accepted")


def run():
    github = MemoryGithub()
    payloads = [b"original raw evidence\n" * 8192, bytes(range(256)) * 600]
    pins = [hashlib.sha256(data).hexdigest() for data in payloads]
    sink = ChunkWriter(github, 1_000_000, lambda *_: None, chunk_bytes=100)
    with gzip.GzipFile(fileobj=sink, mode="wb", mtime=0) as compressor:
        with tarfile.open(
            fileobj=compressor, mode="w|", format=tarfile.USTAR_FORMAT
        ) as archive:
            for pin, data in zip(pins, payloads):
                info = tarfile.TarInfo("objects/" + pin)
                info.size = len(data)
                archive.addfile(info, io.BytesIO(data))
    sink.flush_chunk()
    manifest = {
        "schema": SCHEMA,
        "chunks": sink.rows,
        "objects": [
            {"sha256": pin, "bytes": len(data)} for pin, data in zip(pins, payloads)
        ],
    }
    assert len(sink.rows) > 2
    assert verify_pack(github, manifest)["objects"] == 2
    cases = 1
    with tempfile.TemporaryDirectory() as folder:
        target = Path(folder) / "restored"
        verify_pack(github, manifest, target, pins[0])
        assert target.read_bytes() == payloads[0]
        cases += 1
        reject(lambda: verify_pack(github, manifest, target, pins[0]))
        cases += 1
    for edit in (
        lambda m: m["chunks"][0].update(sha256="0" * 64),
        lambda m: m["chunks"][0].update(bytes=1),
        lambda m: m["objects"][0].update(sha256="0" * 64),
        lambda m: m["objects"][0].update(bytes=1),
        lambda m: m["objects"].append(dict(m["objects"][0])),
        lambda m: m["objects"].pop(),
        lambda m: m.update(schema="different"),
        lambda m: m["chunks"].pop(),
        lambda m: m["chunks"].reverse(),
    ):
        changed = json.loads(encoded(manifest))
        edit(changed)
        reject(lambda: verify_pack(github, changed))
        cases += 1
    original = github.blobs[sink.rows[0]["git_blob"]]
    github.blobs[sink.rows[0]["git_blob"]] = b"changed"
    reject(lambda: verify_pack(github, manifest))
    github.blobs[sink.rows[0]["git_blob"]] = original
    cases += 1
    for path in ("/absolute", "../escape", "a/../escape", "a//b", ""):
        reject(lambda: relative(path))
        cases += 1
    small = ChunkWriter(github, 10, lambda *_: None, chunk_bytes=11)
    reject(lambda: small.write(b"a" * 11))
    cases += 1
    assert keep_local(Path("runs/TIMED_STRENGTH.lock"))
    assert keep_local(Path("runs/full-parallel-strength-v1/matches/a/games/000.json"))
    assert keep_local(Path("runs/example/HOST_SAMPLES.jsonl"))
    assert keep_local(Path("runs/example/SCOPE.json"))
    assert not keep_local(Path("data/searched-full-v3-prepared/train-features.npy"))
    cases += 1
    # Real tar traversal and hardlink members are rejected without extracting.
    for name, kind in (
        ("../escape", tarfile.REGTYPE),
        ("objects/" + pins[0], tarfile.LNKTYPE),
    ):
        output = io.BytesIO()
        with tarfile.open(fileobj=output, mode="w:gz") as archive:
            info = tarfile.TarInfo(name)
            info.type = kind
            archive.addfile(info)
        data = output.getvalue()
        mutated = dict(
            manifest,
            chunks=[
                {
                    "bytes": len(data),
                    "sha256": hashlib.sha256(data).hexdigest(),
                    "git_blob": github.put_blob(data),
                }
            ],
        )
        reject(lambda: verify_pack(github, mutated))
        cases += 1
    with tempfile.TemporaryDirectory() as folder:
        root = Path(folder).resolve()
        work = root / storage.WORK
        work.mkdir(parents=True)
        data = root / "data/example"
        data.mkdir(parents=True)
        for name, contents in (
            ("a", payloads[0]),
            ("b", payloads[0]),
            ("c", payloads[1]),
        ):
            (data / name).write_bytes(contents)
        (data / "a").chmod(0o755)
        for name in ("full-parallel-strength-v1", "full-heuristics-strength-v1"):
            output = root / "runs" / name
            output.mkdir(parents=True)
            (output / "ACTIVE_USAGE.json").write_bytes(encoded({"closed": True}))
        source = Path(storage.__file__)
        plan = {
            "schema": SCHEMA,
            "source_sha256": storage.sha(source),
            "parent_deadline_unix": storage.PARENT,
            "deadline_unix": min(time.time() + 60, storage.PARENT),
            "repository": storage.REPOSITORY,
            "minimum_free_bytes": 0,
            "maximum_files": 20,
            "maximum_logical_input_bytes": 1_000_000,
            "maximum_local_metadata_bytes": 1_000_000,
            "maximum_remote_compressed_bytes": 1_000_000,
            "archive_id": "actual-test",
        }
        plan_path = work / "SCOPE.json"
        plan_path.write_bytes(encoded(plan))
        real = storage.Github
        storage.Github = lambda *_: github
        try:
            storage.Migration(root, plan_path).execute()
            assert not any(data.glob("*"))
            result = json.loads((work / "ARCHIVE_RESULT.json").read_bytes())
            assert result["project_cap_met"] is True
            storage.restore(root, "data/example/a")
            assert (data / "a").read_bytes() == payloads[0]
            assert (data / "a").stat().st_mode & 0o777 == 0o755
            assert not (data / "b").exists()
            cases += 1
            reject(lambda: storage.Migration(root, plan_path).execute())
            cases += 1
        finally:
            storage.Github = real
    return {"status": "passed", "cases": cases, "network_calls": 0, "native_games": 0}


if __name__ == "__main__":
    print(json.dumps(run(), sort_keys=True))
