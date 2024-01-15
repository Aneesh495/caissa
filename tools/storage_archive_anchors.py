"""Keep archive bodies reachable through private blob tags, not large trees.

The main branch binds small manifests only. Immutable data anchors are private
storage references in the archive repository, never product release tags.
"""

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import time

from tools import storage_archive as original
from tools import storage_archive_continuation as previous
from tools.storage_budget import footprint

PREFIX = "archive-blob-v1/"


class Github(previous.Github):
    def __init__(self, repository, check):
        super().__init__(repository, check)
        rows = self.request("GET", "/git/matching-refs/tags/" + PREFIX)
        self.anchors = {row["ref"].removeprefix("refs/tags/"): row for row in rows}

    def anchor(self, row):
        name = PREFIX + row["git_blob"]
        if name in self.anchors:
            ref = self.anchors[name]
        else:
            original.require(
                self.request("GET", "")["private"] is True, "archive privacy changed"
            )
            tag = self.request(
                "POST",
                "/git/tags",
                {
                    "tag": name,
                    "message": "Private exact data archive anchor, not a software release. SHA256 "
                    + row["sha256"],
                    "object": row["git_blob"],
                    "type": "blob",
                },
            )
            original.require(
                tag["object"]["type"] == "blob"
                and tag["object"]["sha"] == row["git_blob"],
                "archive tag target differs",
            )
            self.request(
                "POST", "/git/refs", {"ref": "refs/tags/" + name, "sha": tag["sha"]}
            )
            ref = self.request("GET", "/git/ref/tags/" + name)
        original.require(
            ref["object"]["type"] == "tag", "archive anchor is not an annotated tag"
        )
        target = self.request("GET", "/git/tags/" + ref["object"]["sha"])
        original.require(
            target["object"]["type"] == "blob"
            and target["object"]["sha"] == row["git_blob"],
            "archive anchor points to another object",
        )
        original.require(
            "SHA256 " + row["sha256"] in target["message"],
            "archive anchor checksum differs",
        )
        self.anchors[name] = ref
        return ref["object"]["sha"]

    def commit(self, entries, message):
        manifests = [row for row in entries if row["path"].endswith("/manifest.json")]
        original.require(
            len(manifests) == 1, "archive manifest entry inventory differs"
        )
        manifest = json.loads(self.get_blob(manifests[0]["sha"]))
        expected = {row["git_blob"] for row in manifest["chunks"]}
        actual = {
            row["sha"] for row in entries if not row["path"].endswith("/manifest.json")
        }
        original.require(expected == actual, "archive anchor inventory differs")
        for row in manifest["chunks"]:
            self.anchor(row)
        # This ordinary commit contains the manifest only. Every referenced
        # binary has a separately verified durable Git ref before it is bound.
        return original.Github.commit(
            self, manifests, message + " manifest with private blob anchors"
        )


class Continuation(previous.Continuation):
    def __init__(self, root, amendment_path):
        super().__init__(root, root / original.WORK / "ARCHIVE_CONTINUATION_2.json")
        self.amendment_path = amendment_path.resolve()
        self.amendment = json.loads(self.amendment_path.read_bytes())
        original.require(
            self.amendment["entrypoint_sha256"] == original.sha(__file__),
            "blob-anchor source changed",
        )
        original.require(
            self.amendment["previous_source_sha256"] == original.sha(previous.__file__),
            "previous storage source changed",
        )
        original.require(
            self.amendment["deadline_unix"] == self.plan["deadline_unix"]
            and self.amendment["extra_wall_seconds"] == 0,
            "blob-anchor continuation changes the old deadline",
        )
        for filename, pin in self.amendment["protected_files"].items():
            original.require(
                original.sha(self.work / original.relative(filename)) == pin,
                "protected failed storage record changed: " + filename,
            )
        self.progress.update(
            continuation_source_sha256=original.sha(__file__),
            amendment_sha256=original.sha(self.amendment_path),
            transport="private blob anchors and manifest-only commits",
        )

    def execute(self):
        ledger = self.work / "ARCHIVE_CONTINUATION_USAGE_3.json"
        original.require(not ledger.exists(), "blob-anchor invocation already recorded")
        for name in ("ARCHIVE_USAGE.json", "ARCHIVE_CONTINUATION_USAGE_2.json"):
            original.require(
                json.loads((self.work / name).read_bytes())["closed"] is True,
                "older storage owner remains active",
            )
        for name in ("full-parallel-strength-v1", "full-heuristics-strength-v1"):
            original.require(
                json.loads(
                    (self.root / "runs" / name / "ACTIVE_USAGE.json").read_bytes()
                )["closed"]
                is True,
                "timed owner ledger remains open",
            )
        self.lease = original.HostLease(self.root / "runs")
        usage = {
            "started_unix": self.started,
            "closed": False,
            "invocations_started": 1,
            "effective_storage_invocations": 3,
            "extra_wall_seconds": 0,
            "amendment_sha256": original.sha(self.amendment_path),
        }
        original.atomic(ledger, usage)
        try:
            github = Github(original.REPOSITORY, self.check)
            packs = previous.grouping(self.work / "INVENTORY.jsonl")
            total = 0
            for number, objects in enumerate(packs):
                receipt_path = self.work / (
                    "PACK-" + str(number).zfill(5) + "-VERIFIED.json"
                )
                if receipt_path.exists():
                    receipt = json.loads(receipt_path.read_bytes())
                    original.require(
                        receipt["eviction_complete"] is True,
                        "partial old eviction needs reconciliation",
                    )
                    original.require(
                        all(
                            not (self.root / row[0]).exists()
                            for _, rows in objects
                            for row in rows
                        ),
                        "evicted path reappeared",
                    )
                    total += receipt["compressed_bytes"]
                    continue
                uploading = self.work / (
                    "PACK-" + str(number).zfill(5) + "-UPLOADING.json"
                )
                if uploading.exists():
                    original.require(
                        number == self.amendment["reuse_complete_pack"],
                        "unexpected old partial pack",
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
                receipt = json.loads(receipt_path.read_bytes())
                receipt.update(
                    transport="private blob anchors and manifest-only commit",
                    anchor_prefix="refs/tags/" + PREFIX,
                    software_release=False,
                )
                original.atomic(receipt_path, receipt)
                self.report(
                    remote_compressed_bytes=total, reused_git_blobs=github.reused_blobs
                )
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
                phase="blob-anchor-continuation-failed-preserving-unverified-inputs",
                error_type=type(error).__name__,
                error=str(error),
            )
            original.atomic(
                self.work / ("ARCHIVE_ANCHOR_FAILED-" + str(time.time_ns()) + ".json"),
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
