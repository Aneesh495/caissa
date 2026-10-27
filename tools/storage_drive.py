"""Bounded private Drive archive using the connected-tool file-transfer bridge.

No account credentials are extracted. The bridge supplies short-lived download
references, kept only in an owner-private directory and never in process args.
Every full pack is remotely reconstructed before original files are removed.
"""

import argparse
import gzip
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tarfile
import time

from tools import storage_archive as codec
from tools.storage_archive_continuation import grouping
from tools.storage_budget import footprint

WORK = codec.WORK
FOLDER = "1VIh5amtHhs1_LXdCDNzAtdOVNtjLW-PC"


def private_json(path, value):
    codec.atomic(path, value)
    path.chmod(0o600)


class Bridge:
    def __init__(self, work, check):
        self.work, self.check = work, check
        self.directory = work / "drive-bridge"
        self.directory.mkdir(mode=0o700, exist_ok=True)
        self.directory.chmod(0o700)
        self.counter = 0

    def call(self, operation, **arguments):
        self.counter += 1
        request_id = str(self.counter).zfill(7)
        response = self.directory / (request_id + ".response.json")
        codec.require(not response.exists(), "Drive bridge response already exists")
        private_json(
            self.directory / "REQUEST.json",
            {
                "schema": "caissa-drive-bridge-v1",
                "id": request_id,
                "operation": operation,
                **arguments,
            },
        )
        while True:
            self.check()
            if response.exists():
                try:
                    result = json.loads(response.read_bytes())
                except json.JSONDecodeError:
                    time.sleep(0.1)
                    continue
                codec.require(
                    result.get("id") == request_id,
                    "Drive bridge response identity differs",
                )
                (self.directory / "REQUEST.json").unlink()
                response.unlink()
                codec.require(
                    result.get("status") == "ok",
                    "connected Drive transfer failed: "
                    + str(result.get("error", "unspecified"))[:200],
                )
                return result
            time.sleep(0.25)


class Drive:
    def __init__(self, owner):
        self.owner = owner
        self.bridge = Bridge(owner.work, owner.check)
        self.spool = owner.work / "drive-spool"
        self.spool.mkdir(mode=0o700, exist_ok=True)
        self.spool.chmod(0o700)
        self.objects = {}
        self.uploaded = 0

    def put_blob(self, data, name):
        self.owner.check()
        codec.require(
            self.uploaded + len(data) <= self.owner.plan["maximum_new_drive_bytes"],
            "new Drive archive byte ceiling exhausted",
        )
        pin = hashlib.sha256(data).hexdigest()
        oid = codec.blob_oid(data)
        source = self.spool / "upload.bin"
        codec.require(not source.exists(), "Drive upload staging already exists")
        source.write_bytes(data)
        source.chmod(0o600)
        try:
            result = self.bridge.call(
                "upload",
                source_path=str(source),
                file_name=name,
                expected_bytes=len(data),
                expected_sha256=pin,
                folder_id=FOLDER,
            )
            codec.require(
                result["bytes"] == len(data)
                and result["folder_id"] == FOLDER
                and result["private_owner_only"] is True,
                "Drive upload metadata differs",
            )
            self.uploaded += len(data)
            row = {
                "git_blob": oid,
                "bytes": len(data),
                "sha256": pin,
                "drive_file_id": result["file_id"],
            }
            self.objects[oid] = row
            return oid
        finally:
            source.unlink(missing_ok=True)

    def get_blob(self, oid):
        row = self.objects[oid]
        response = self.bridge.call(
            "fetch", file_id=row["drive_file_id"], expected_bytes=row["bytes"]
        )
        config = self.spool / "download.conf"
        destination = self.spool / "download.bin"
        codec.require(
            not config.exists() and not destination.exists(),
            "Drive download staging already exists",
        )
        config.write_text(
            "url = "
            + json.dumps(response["download_url"])
            + "\noutput = "
            + json.dumps(str(destination))
            + "\nsilent\nshow-error\nfail\nmax-time = 120\nmax-filesize = "
            + str(row["bytes"])
            + "\n"
        )
        config.chmod(0o600)
        try:
            self.owner.check()
            result = subprocess.run(
                ["curl", "--config", str(config)], capture_output=True, timeout=125
            )
            codec.require(
                result.returncode == 0,
                "authenticated Drive readback failed, curl exit "
                + str(result.returncode),
            )
            data = destination.read_bytes()
            codec.require(
                len(data) == row["bytes"]
                and hashlib.sha256(data).hexdigest() == row["sha256"]
                and codec.blob_oid(data) == oid,
                "Drive raw file readback differs",
            )
            return data
        finally:
            config.unlink(missing_ok=True)
            destination.unlink(missing_ok=True)


class Migration:
    def __init__(self, root, plan_path):
        self.root, self.plan_path = root.resolve(), plan_path.resolve()
        self.work = self.root / WORK
        self.plan = json.loads(self.plan_path.read_bytes())
        codec.require(
            self.plan["source_sha256"] == codec.sha(__file__),
            "Drive archive source changed",
        )
        codec.require(
            self.plan["codec_sha256"] == codec.sha(codec.__file__),
            "original archive codec changed",
        )
        codec.require(
            self.plan["parent_deadline_unix"] == codec.PARENT
            and self.plan["deadline_unix"] <= codec.PARENT,
            "Drive archive parent deadline differs",
        )
        codec.require(
            self.plan["folder_id"] == FOLDER, "Drive archive destination differs"
        )
        for name, pin in self.plan["protected_files"].items():
            codec.require(
                codec.sha(self.work / codec.relative(name)) == pin,
                "preserved storage evidence changed: " + name,
            )
        self.started = time.time()
        self.progress = {
            "phase": "admitting-drive-backend",
            "source_sha256": codec.sha(__file__),
            "scope_sha256": codec.sha(self.plan_path),
        }
        self.check()

    def check(self):
        codec.require(
            time.time() < self.plan["deadline_unix"],
            "Drive archive fixed deadline exhausted",
        )
        codec.require(
            shutil.disk_usage(self.root).free >= self.plan["minimum_free_bytes"],
            "Drive archive disk reserve exhausted",
        )
        if hasattr(self, "lease"):
            self.lease.check()

    def report(self, **values):
        self.progress.update(values, observed_unix=time.time())
        codec.atomic(self.work / "DRIVE_ARCHIVE_PROGRESS.json", self.progress)

    def pack(self, drive, number, objects):
        self.report(phase="compressing-and-uploading-to-private-drive", pack=number)
        prefix = self.plan["archive_id"] + "-pack-" + str(number).zfill(5)

        class Upload:
            def put_blob(inner, data):
                return drive.put_blob(
                    data, prefix + "-part-" + str(len(sink.rows)).zfill(5) + ".bin"
                )

        def checkpoint(rows, size):
            full = [
                {
                    **row,
                    "drive_file_id": drive.objects[row["git_blob"]]["drive_file_id"],
                }
                for row in rows
            ]
            codec.atomic(
                self.work / ("DRIVE_PACK-" + str(number).zfill(5) + "-UPLOADING.json"),
                {"pack": number, "chunks": full, "compressed_bytes": size},
            )
            self.report(
                pack=number,
                uploaded_chunks=len(rows),
                compressed_pack_bytes=size,
                new_drive_uploaded_bytes=drive.uploaded,
            )

        sink = codec.ChunkWriter(
            Upload(), self.plan["maximum_new_drive_bytes"] - drive.uploaded, checkpoint
        )
        with gzip.GzipFile(
            fileobj=sink, mode="wb", compresslevel=3, mtime=0
        ) as compressor:
            with tarfile.open(
                fileobj=compressor, mode="w|", format=tarfile.USTAR_FORMAT
            ) as archive:
                for pin, rows in objects:
                    first = rows[0]
                    path = self.root / codec.relative(first[0])
                    codec.require(
                        codec.identity(path) == first[1:],
                        "Drive source changed before packing",
                    )
                    member = tarfile.TarInfo("objects/" + pin)
                    member.size, member.mode, member.mtime = first[1], 0o600, 0
                    with path.open("rb") as source:
                        archive.addfile(member, source)
                    codec.require(
                        codec.identity(path) == first[1:],
                        "Drive source changed during packing",
                    )
        sink.flush_chunk()
        manifest = {
            "schema": codec.SCHEMA,
            "provider": "google-drive-private",
            "folder_id": FOLDER,
            "source_sha256": self.plan["source_sha256"],
            "archive_id": self.plan["archive_id"],
            "pack": number,
            "chunks": [
                {
                    **row,
                    "drive_file_id": drive.objects[row["git_blob"]]["drive_file_id"],
                }
                for row in sink.rows
            ],
            "objects": [{"sha256": pin, "bytes": rows[0][1]} for pin, rows in objects],
            "paths": [[pin, *row] for pin, rows in objects for row in rows],
            "full_acceptance": False,
        }
        raw = codec.encoded(manifest)
        stored = gzip.compress(raw, compresslevel=3, mtime=0)
        codec.require(
            len(raw) <= 64_000_000 and len(stored) <= codec.CHUNK,
            "Drive manifest ceiling exhausted",
        )
        oid = drive.put_blob(stored, prefix + "-manifest.json.gz")
        binding = drive.objects[oid]
        self.report(phase="reading-back-private-drive-manifest", pack=number)
        readback = drive.get_blob(oid)
        codec.require(
            readback == stored and gzip.decompress(readback) == raw,
            "Drive stored manifest differs",
        )
        recovered = json.loads(gzip.decompress(readback))
        drive.objects = {row["git_blob"]: row for row in recovered["chunks"]}
        self.report(phase="independently-reconstructing-full-drive-pack", pack=number)
        result = codec.verify_pack(drive, recovered)
        receipt = {
            "provider": "google-drive-private",
            "pack": number,
            "manifest_file_id": binding["drive_file_id"],
            "manifest_stored_bytes": binding["bytes"],
            "manifest_stored_sha256": binding["sha256"],
            "manifest_raw_sha256": hashlib.sha256(raw).hexdigest(),
            "compressed_bytes": sink.size,
            "result": result,
            "eviction_complete": False,
            "observed_unix": time.time(),
        }
        receipt_path = self.work / (
            "DRIVE_PACK-" + str(number).zfill(5) + "-VERIFIED.json"
        )
        codec.atomic(receipt_path, receipt)
        with (self.work / "DRIVE_RESTORE_CATALOG.jsonl").open("ab") as catalog:
            for pin, rows in objects:
                for row in rows:
                    catalog.write(
                        codec.encoded(
                            {
                                "provider": "google-drive-private",
                                "path": row[0],
                                "sha256": pin,
                                "bytes": row[1],
                                "mode": row[2],
                                "mtime_ns": row[3],
                                "pack": number,
                                "manifest_file_id": binding["drive_file_id"],
                                "manifest_stored_bytes": binding["bytes"],
                                "manifest_stored_sha256": binding["sha256"],
                            }
                        )
                    )
            catalog.flush()
            os.fsync(catalog.fileno())
        removed = 0
        for pin, rows in objects:
            for row in rows:
                self.check()
                path = self.root / codec.relative(row[0])
                codec.require(
                    path.resolve().is_relative_to(self.root)
                    and codec.identity(path) == row[1:],
                    "Drive local input changed before eviction",
                )
                codec.require(
                    codec.sha(path, self.check) == pin
                    and codec.identity(path) == row[1:],
                    "Drive local input bytes changed before eviction",
                )
                path.unlink()
                removed += row[1]
        receipt.update(
            eviction_complete=True,
            removed_logical_bytes=removed,
            completed_unix=time.time(),
        )
        codec.atomic(receipt_path, receipt)
        drive.objects = {}
        self.report(
            phase="drive-pack-verified-and-evicted",
            pack=number,
            removed_logical_bytes=removed,
            new_drive_uploaded_bytes=drive.uploaded,
        )

    def execute(self):
        ledger = self.work / "DRIVE_ARCHIVE_USAGE.json"
        codec.require(not ledger.exists(), "Drive archive invocation already recorded")
        for name in (
            "ARCHIVE_USAGE.json",
            "ARCHIVE_CONTINUATION_USAGE_2.json",
            "ARCHIVE_CONTINUATION_USAGE_3.json",
        ):
            codec.require(
                json.loads((self.work / name).read_bytes())["closed"] is True,
                "GitHub archive owner still active",
            )
        for name in ("full-heuristics-strength-v1", "full-parallel-strength-v1"):
            codec.require(
                json.loads(
                    (self.root / "runs" / name / "ACTIVE_USAGE.json").read_bytes()
                )["closed"]
                is True,
                "timed owner still active",
            )
        self.lease = codec.HostLease(self.root / "runs")
        usage = {
            "started_unix": self.started,
            "closed": False,
            "invocations_started": 1,
            "scope_sha256": codec.sha(self.plan_path),
            "source_sha256": codec.sha(__file__),
        }
        codec.atomic(ledger, usage)
        try:
            drive = Drive(self)
            packs = grouping(self.work / "INVENTORY.jsonl")
            for number, objects in enumerate(packs):
                old_receipt = self.work / (
                    "PACK-" + str(number).zfill(5) + "-VERIFIED.json"
                )
                if old_receipt.exists():
                    saved = json.loads(old_receipt.read_bytes())
                    codec.require(
                        saved["eviction_complete"] is True
                        and all(
                            not (self.root / row[0]).exists()
                            for _, rows in objects
                            for row in rows
                        ),
                        "old verified eviction differs",
                    )
                    continue
                self.pack(drive, number, objects)
            measured = footprint([self.root])
            self.report(
                phase="drive-archive-selected-inputs-complete",
                project_footprint=measured,
                mac_used_bytes=shutil.disk_usage(self.root).used,
                project_cap_met=measured["charged_bytes"] <= codec.PROJECT_CAP,
                mac_cap_met=shutil.disk_usage(self.root).used <= codec.MAC_CAP,
            )
            codec.atomic(self.work / "DRIVE_ARCHIVE_RESULT.json", self.progress)
        except BaseException as error:
            self.report(
                phase="drive-archive-failed-preserving-unverified-originals",
                error_type=type(error).__name__,
                error=str(error),
            )
            codec.atomic(
                self.work / ("DRIVE_ARCHIVE_FAILED-" + str(time.time_ns()) + ".json"),
                self.progress,
            )
            raise
        finally:
            usage.update(closed=True, ended_unix=time.time())
            codec.atomic(ledger, usage)
            self.lease.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--plan", type=Path, required=True)
    args = parser.parse_args()
    Migration(args.root.resolve(), args.plan).execute()
