"""Resume the preserved storage inventory with bounded private ref updates.

The original failure, usage ledger, chunks and deadline are preserved. An
explicit amendment grants one additional invocation, not a fresh time budget.
"""

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import time

from tools import storage_archive as original
from tools.storage_budget import footprint


def batches(entries):
    manifests = [row for row in entries if row["path"].endswith("/manifest.json")]
    chunks = [row for row in entries if not row["path"].endswith("/manifest.json")]
    original.require(len(manifests) == 1, "archive batch manifest inventory differs")
    original.require(
        len({row["path"] for row in entries}) == len(entries), "duplicate archive entry"
    )
    # Each existing chunk is <=32MiB and a manifest <=40MB. Fourteen chunks
    # plus a manifest stay below512MiB and the documented2GBref-update limit.
    groups = [chunks[index : index + 14] for index in range(0, len(chunks), 14)]
    if not groups:
        groups = [[]]
    groups[-1].extend(manifests)
    return groups


class Github(original.Github):
    def __init__(self, repository, check):
        super().__init__(repository, check)
        self.reuse = None
        self.reused_blobs = 0

    def put_blob(self, data):
        if self.reuse is None:
            return super().put_blob(data)
        original.require(bool(self.reuse), "reused archive chunk inventory exhausted")
        row = self.reuse.pop(0)
        original.require(
            len(data) == row["bytes"]
            and hashlib.sha256(data).hexdigest() == row["sha256"]
            and original.blob_oid(data) == row["git_blob"],
            "recompressed archived chunk differs; no substitution/upload",
        )
        self.reused_blobs += 1
        return row["git_blob"]

    def commit(self, entries, message):
        for number, group in enumerate(batches(entries)):
            result = super().commit(group, message + " reachable batch " + str(number))
        return result


def grouping(inventory):
    groups = {}
    with inventory.open("rb") as stream:
        for line in stream:
            pin, *row = json.loads(line)
            original.relative(row[0])
            groups.setdefault(pin, []).append(row)
    packs, current, size = [], [], 0
    for pin, rows in sorted(groups.items(), key=lambda item: (-item[1][0][1], item[0])):
        amount = rows[0][1]
        if current and size + amount > original.PACK:
            packs.append(current)
            current, size = [], 0
        current.append((pin, rows))
        size += amount
    if current:
        packs.append(current)
    return packs


def manifest_for(plan, number, objects, chunks):
    return {
        "schema": original.SCHEMA,
        "archive_id": plan["archive_id"],
        "pack": number,
        "source_sha256": plan["source_sha256"],
        "chunks": chunks,
        "objects": [{"sha256": pin, "bytes": rows[0][1]} for pin, rows in objects],
        "paths": [[pin, *row] for pin, rows in objects for row in rows],
        "original_bytes_and_modes_preserved": True,
        "storage_transport_only": True,
        "full_acceptance": False,
    }


class Continuation(original.Migration):
    def __init__(self, root, amendment_path):
        self.amendment_path = amendment_path.resolve()
        self.amendment = json.loads(self.amendment_path.read_bytes())
        super().__init__(root, root / original.WORK / "ARCHIVE_SCOPE.json")
        original.require(
            self.amendment["entrypoint_sha256"] == original.sha(__file__),
            "archive continuation source changed",
        )
        original.require(
            self.amendment["original_source_sha256"] == original.sha(original.__file__),
            "original archive source changed",
        )
        original.require(
            self.amendment["original_scope_sha256"] == original.sha(self.plan_path),
            "original archive scope changed",
        )
        original.require(
            self.amendment["deadline_unix"] == self.plan["deadline_unix"]
            and self.amendment["extra_wall_seconds"] == 0,
            "archive continuation changes the old deadline",
        )
        for filename, pin in self.amendment["protected_files"].items():
            original.require(
                original.sha(self.work / original.relative(filename)) == pin,
                "original storage evidence changed: " + filename,
            )
        self.progress.update(
            continuation_source_sha256=original.sha(__file__),
            amendment_sha256=original.sha(self.amendment_path),
        )

    def existing(self, github, number, objects):
        saved = json.loads(
            (
                self.work / ("PACK-" + str(number).zfill(5) + "-UPLOADING.json")
            ).read_bytes()
        )
        original.require(
            saved["pack"] == number
            and saved["compressed_bytes"]
            == sum(row["bytes"] for row in saved["chunks"]),
            "old chunk checkpoint differs",
        )
        manifest = manifest_for(self.plan, number, objects, saved["chunks"])
        raw = original.encoded(manifest)
        oid = original.blob_oid(raw)
        # The failed ref update had already uploaded this exact manifest. Its
        # presence distinguishes a complete gzip stream from a partial upload.
        original.require(
            github.get_blob(oid) == raw, "old complete pack manifest absent/different"
        )
        github.reuse = [
            *saved["chunks"],
            {
                "bytes": len(raw),
                "sha256": hashlib.sha256(raw).hexdigest(),
                "git_blob": oid,
            },
        ]

    def execute(self):
        ledger = self.work / "ARCHIVE_CONTINUATION_USAGE_2.json"
        original.require(
            not ledger.exists(), "archive continuation invocation already recorded"
        )
        original.require(
            json.loads((self.work / "ARCHIVE_USAGE.json").read_bytes())["closed"]
            is True,
            "original storage owner still active",
        )
        for name in ("full-parallel-strength-v1", "full-heuristics-strength-v1"):
            original.require(
                json.loads(
                    (self.root / "runs" / name / "ACTIVE_USAGE.json").read_bytes()
                )["closed"]
                is True,
                "timed ledger still open",
            )
        self.lease = original.HostLease(self.root / "runs")
        usage = {
            "started_unix": self.started,
            "closed": False,
            "invocations_started": 1,
            "effective_storage_invocations": 2,
            "extra_wall_seconds": 0,
            "amendment_sha256": original.sha(self.amendment_path),
        }
        original.atomic(ledger, usage)
        try:
            github = Github(original.REPOSITORY, self.check)
            packs = grouping(self.work / "INVENTORY.jsonl")
            total = 0
            for number, objects in enumerate(packs):
                receipt_path = self.work / (
                    "PACK-" + str(number).zfill(5) + "-VERIFIED.json"
                )
                if receipt_path.exists():
                    receipt = json.loads(receipt_path.read_bytes())
                    original.require(
                        receipt["eviction_complete"] is True,
                        "partial eviction requires explicit reconciliation",
                    )
                    original.require(
                        all(
                            not (self.root / row[0]).exists()
                            for _, rows in objects
                            for row in rows
                        ),
                        "previously evicted path reappeared",
                    )
                    total += receipt["compressed_bytes"]
                    continue
                uploading = self.work / (
                    "PACK-" + str(number).zfill(5) + "-UPLOADING.json"
                )
                if uploading.exists():
                    original.require(
                        number == self.amendment["reuse_complete_pack"],
                        "unexpected old partial upload",
                    )
                    self.existing(github, number, objects)
                total += self.pack(
                    github,
                    number,
                    objects,
                    self.plan["maximum_remote_compressed_bytes"] - total,
                )
                original.require(
                    github.reuse is None or not github.reuse,
                    "old chunk inventory not consumed",
                )
                github.reuse = None
                self.report(
                    remote_compressed_bytes=total, reused_git_blobs=github.reused_blobs
                )
            for base in self.root.iterdir():
                if base.is_dir() and not original.keep_local(
                    base.relative_to(self.root)
                ):
                    import os

                    for directory, _, _ in os.walk(base, topdown=False):
                        try:
                            Path(directory).rmdir()
                        except OSError:
                            pass
            measured = footprint([self.root])
            disk = shutil.disk_usage(self.root)
            self.report(
                phase="archive-migration-complete",
                packs=len(packs),
                remote_compressed_bytes=total,
                project_charged_bytes=measured["charged_bytes"],
                project_allocated_bytes=measured["allocated_bytes"],
                project_logical_bytes=measured["logical_bytes"],
                mac_used_bytes=disk.used,
                project_cap_met=measured["charged_bytes"] <= original.PROJECT_CAP,
                mac_cap_met=disk.used <= original.MAC_CAP,
            )
            original.atomic(self.work / "ARCHIVE_RESULT.json", self.progress)
        except BaseException as error:
            self.report(
                phase="continuation-failed-preserving-unverified-inputs",
                error_type=type(error).__name__,
                error=str(error),
            )
            original.atomic(
                self.work
                / ("ARCHIVE_CONTINUATION_FAILED-" + str(time.time_ns()) + ".json"),
                self.progress,
            )
            raise
        finally:
            usage.update(closed=True, ended_unix=time.time())
            original.atomic(ledger, usage)
            self.lease.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--amendment", type=Path, required=True)
    args = parser.parse_args()
    Continuation(args.root.resolve(), args.amendment).execute()
