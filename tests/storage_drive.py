"""Actual pack/provider/readback/deletion controls without cloud writes."""

import hashlib
import json
from pathlib import Path
import shutil
import tempfile
import threading
import time

from tools import storage_archive as codec
from tools import storage_drive as storage


class FakeBridge:
    def __init__(self, owner, fault=None):
        self.owner, self.fault, self.files = owner, fault, {}
        self.folder = owner.root / "fake-provider"
        self.folder.mkdir(exist_ok=True)

    def call(self, operation, **args):
        if operation == "upload":
            file_id = "file" + str(len(self.files))
            path = self.folder / file_id
            shutil.copyfile(args["source_path"], path)
            assert codec.sha(path) == args["expected_sha256"]
            self.files[file_id] = path
            return {
                "file_id": file_id,
                "bytes": path.stat().st_size,
                "folder_id": storage.FOLDER,
                "private_owner_only": self.fault != "public",
            }
        path = self.files[args["file_id"]]
        if self.fault == "corrupt":
            path.write_bytes(b"changed")
        if self.fault == "source-changed":
            (self.owner.root / "data/a").write_bytes(b"new unverified user bytes")
        return {"download_url": path.as_uri()}


def owner(root):
    instance = storage.Migration.__new__(storage.Migration)
    instance.root = root
    instance.work = root / "work"
    instance.work.mkdir()
    instance.plan = {
        "deadline_unix": time.time() + 60,
        "minimum_free_bytes": 0,
        "maximum_new_drive_bytes": 2_000_000,
        "archive_id": "test",
        "source_sha256": codec.sha(storage.__file__),
    }
    instance.progress = {}
    return instance


def rejects(function):
    try:
        function()
    except ValueError:
        return
    raise AssertionError("changed archive accepted")


def run():
    cases = 0
    for fault in (None, "corrupt", "public", "source-changed"):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder).resolve()
            instance = owner(root)
            (root / "data").mkdir()
            first, other = b"exact evidence" * 8192, b"second witness" * 1024
            for name, raw in (("a", first), ("b", first), ("c", other)):
                (root / "data" / name).write_bytes(raw)
            objects = []
            for names in (("a", "b"), ("c",)):
                pin = codec.sha(root / "data" / names[0])
                objects.append(
                    (
                        pin,
                        [
                            ["data/" + name, *codec.identity(root / "data" / name)]
                            for name in names
                        ],
                    )
                )
            drive = storage.Drive(instance)
            drive.bridge = FakeBridge(instance, fault)
            if fault is None:
                instance.pack(drive, 1, objects)
                assert not list((root / "data").iterdir())
                receipt = json.loads(
                    (instance.work / "DRIVE_PACK-00001-VERIFIED.json").read_bytes()
                )
                assert (
                    receipt["eviction_complete"] is True
                    and receipt["result"]["objects"] == 2
                )
                rows = [
                    json.loads(line)
                    for line in (instance.work / "DRIVE_RESTORE_CATALOG.jsonl")
                    .read_text()
                    .splitlines()
                ]
                assert len(rows) == 3 and {row["path"] for row in rows} == {
                    "data/a",
                    "data/b",
                    "data/c",
                }
                assert all(row["provider"] == "google-drive-private" for row in rows)
                assert not list(drive.spool.iterdir())
                cases += 3
            else:
                rejects(lambda: instance.pack(drive, 1, objects))
                assert all((root / "data" / name).exists() for name in ("a", "b", "c"))
                assert not list(drive.spool.iterdir())
                cases += 1
            instance.plan["maximum_new_drive_bytes"] = 1
            rejects(lambda: drive.put_blob(b"over quota", "quota.bin"))
            cases += 1
    with tempfile.TemporaryDirectory() as folder:
        root = Path(folder).resolve()
        instance = owner(root)
        bridge = storage.Bridge(instance.work, instance.check)

        def respond():
            path = bridge.directory / "REQUEST.json"
            while not path.exists():
                time.sleep(0.01)
            codec.atomic(
                bridge.directory / "0000001.response.json",
                {"id": "wrong", "status": "ok"},
            )

        thread = threading.Thread(target=respond)
        thread.start()
        rejects(lambda: bridge.call("upload", source_path="not-used"))
        thread.join(timeout=2)
        cases += 1
    return {"status": "passed", "cases": cases, "cloud_writes": 0, "native_games": 0}


if __name__ == "__main__":
    print(json.dumps(run(), sort_keys=True))
