"""One explicit Drive continuation with finite, recorded transport retries."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import time

from tools import storage_drive as previous
from tools.storage_budget import footprint

codec = previous.codec
TRANSIENT_CURL = {18, 28, 52, 55, 56}


class ContinuedBridge(previous.Bridge):
    def __init__(self, work, check):
        super().__init__(work, check)
        codec.require(
            not (self.directory / "REQUEST.json").exists(),
            "unresolved prior bridge request requires reconciliation",
        )
        self.counter = max(
            (
                int(path.name.split(".")[0])
                for path in self.directory.glob("*.controller.json")
            ),
            default=0,
        )


def diagnostic(owner, row, attempt, result, destination):
    # Never retain the bearer URL, config body, headers or raw process arguments.
    raw = result.stderr or b""
    text = raw.decode("utf-8", errors="replace")
    text = re.sub(r"https?://\S+", "[URL omitted]", text)
    text = re.sub(r"(?i)(authorization|cookie):[^\r\n]*", r"\1: [omitted]", text)
    part = destination.read_bytes() if destination.exists() else b""
    record = {
        "file_id": row["drive_file_id"],
        "expected_bytes": row["bytes"],
        "attempt": attempt,
        "curl_exit": result.returncode,
        "sanitized_stderr": text[:2000],
        "original_stderr_sha256": hashlib.sha256(raw).hexdigest(),
        "partial_bytes": len(part),
        "partial_sha256": hashlib.sha256(part).hexdigest(),
        "observed_unix": time.time(),
    }
    path = owner.work / ("DRIVE_READBACK_2-" + str(time.time_ns()) + ".json")
    previous.private_json(path, record)


class ContinuedDrive(previous.Drive):
    def __init__(self, owner):
        super().__init__(owner)
        self.bridge = ContinuedBridge(owner.work, owner.check)
        self.uploaded = owner.amendment["prior_uploaded_bytes"]
        self.reuse = []
        self.reused_bytes = 0

    def put_blob(self, data, name):
        self.owner.check()
        if self.reuse:
            row = self.reuse[0]
            codec.require(
                len(data) == row["bytes"]
                and hashlib.sha256(data).hexdigest() == row["sha256"]
                and codec.blob_oid(data) == row["git_blob"],
                "recompressed existing Drive chunk differs",
            )
            self.reuse.pop(0)
            self.objects[row["git_blob"]] = row
            self.reused_bytes += len(data)
            return row["git_blob"]
        old_prefix = (
            self.owner.plan["archive_id"]
            + "-pack-"
            + str(self.owner.amendment["reuse_pack"]).zfill(5)
            + "-part-"
        )
        codec.require(
            not name.startswith(old_prefix),
            "complete reused pack contains an unexpected extra chunk",
        )
        if name.endswith("-manifest.json.gz"):
            name = name.removesuffix(".json.gz") + "-continuation-2.json.gz"
        return super().put_blob(data, name)

    def get_blob(self, oid):
        row = self.objects[oid]
        for attempt in range(
            1, self.owner.amendment["maximum_download_attempts_per_object"] + 1
        ):
            self.owner.check()
            response = self.bridge.call(
                "fetch", file_id=row["drive_file_id"], expected_bytes=row["bytes"]
            )
            config = self.spool / "download.conf"
            destination = self.spool / "download.bin"
            codec.require(
                not config.exists() and not destination.exists(),
                "download staging already exists",
            )
            remaining = self.owner.plan["deadline_unix"] - time.time()
            codec.require(
                remaining > 1, "fixed Drive deadline exhausted before download"
            )
            timeout = min(120, remaining)
            config.write_text(
                "url = "
                + json.dumps(response["download_url"])
                + "\noutput = "
                + json.dumps(str(destination))
                + "\nsilent\nshow-error\nfail\nmax-time = "
                + str(timeout)
                + "\nmax-filesize = "
                + str(row["bytes"])
                + "\n"
            )
            config.chmod(0o600)
            try:
                self.owner.check()
                result = subprocess.run(
                    ["curl", "--config", str(config)],
                    capture_output=True,
                    timeout=timeout + 5,
                )
                if result.returncode:
                    diagnostic(self.owner, row, attempt, result, destination)
                    codec.require(
                        result.returncode in TRANSIENT_CURL
                        and attempt
                        < self.owner.amendment["maximum_download_attempts_per_object"],
                        "Drive readback failed after bounded attempts, curl exit "
                        + str(result.returncode),
                    )
                    continue
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
        raise ValueError("bounded Drive attempts exhausted")


class Continuation(previous.Migration):
    def __init__(self, root, amendment):
        self.amendment_path = amendment.resolve()
        self.amendment = json.loads(self.amendment_path.read_bytes())
        super().__init__(root, root / previous.WORK / "DRIVE_ARCHIVE_SCOPE.json")
        codec.require(
            self.amendment["entrypoint_sha256"] == codec.sha(__file__),
            "continuation source differs",
        )
        codec.require(
            self.amendment["original_scope_sha256"] == codec.sha(self.plan_path)
            and self.amendment["deadline_unix"] == self.plan["deadline_unix"]
            and self.amendment["extra_wall_seconds"] == 0
            and self.amendment["extra_remote_ceiling_bytes"] == 0
            and self.amendment["extra_backend_starts"] == 1
            and self.amendment["maximum_download_attempts_per_object"] == 3,
            "continuation finite allowance differs",
        )
        for name, pin in self.amendment["protected_files"].items():
            codec.require(
                codec.sha(self.work / codec.relative(name)) == pin,
                "old Drive evidence differs: " + name,
            )
        codec.require(
            codec.sha(root / self.amendment["controller_path"])
            == self.amendment["controller_sha256"],
            "continuation controller source differs",
        )
        self.progress.update(
            continuation_source_sha256=codec.sha(__file__),
            amendment_sha256=codec.sha(self.amendment_path),
        )

    def report(self, **values):
        self.progress.update(values, observed_unix=time.time())
        codec.atomic(self.work / "DRIVE_CONTINUATION_PROGRESS_2.json", self.progress)

    def execute(self):
        ledger = self.work / "DRIVE_CONTINUATION_USAGE_2.json"
        codec.require(not ledger.exists(), "Drive continuation start already consumed")
        codec.require(
            json.loads((self.work / "DRIVE_ARCHIVE_USAGE.json").read_bytes())["closed"],
            "previous Drive owner still active",
        )
        for name in ("full-parallel-strength-v1", "full-heuristics-strength-v1"):
            codec.require(
                json.loads(
                    (self.root / "runs" / name / "ACTIVE_USAGE.json").read_bytes()
                )["closed"],
                "chess ledger remains open",
            )
        self.lease = codec.HostLease(self.root / "runs")
        usage = {
            "closed": False,
            "started_unix": time.time(),
            "invocations_started": 1,
            "effective_drive_starts": 2,
            "amendment_sha256": codec.sha(self.amendment_path),
            "extra_wall_seconds": 0,
        }
        codec.atomic(ledger, usage)
        original_atomic = codec.atomic

        def separate_checkpoint(path, value):
            path = Path(path)
            if (
                path.parent == self.work
                and path.name.startswith("DRIVE_PACK-")
                and path.name.endswith("-UPLOADING.json")
            ):
                path = path.with_name("DRIVE_CONTINUATION_2_" + path.name)
            return original_atomic(path, value)

        codec.atomic = separate_checkpoint
        try:
            drive = ContinuedDrive(self)
            for number, objects in enumerate(
                previous.grouping(self.work / "INVENTORY.jsonl")
            ):
                accepted = [
                    self.work / (prefix + str(number).zfill(5) + "-VERIFIED.json")
                    for prefix in ("PACK-", "DRIVE_PACK-")
                ]
                receipt = next((p for p in accepted if p.exists()), None)
                if receipt is not None:
                    codec.require(
                        json.loads(receipt.read_bytes())["eviction_complete"] is True,
                        "partial eviction requires reconciliation",
                    )
                    codec.require(
                        all(
                            not (self.root / row[0]).exists()
                            for _, rows in objects
                            for row in rows
                        ),
                        "evicted original reappeared",
                    )
                    continue
                checkpoint = self.work / (
                    "DRIVE_PACK-" + str(number).zfill(5) + "-UPLOADING.json"
                )
                if checkpoint.exists():
                    codec.require(
                        number == self.amendment["reuse_pack"],
                        "unexpected old partial pack",
                    )
                    saved = json.loads(checkpoint.read_bytes())
                    codec.require(
                        saved["pack"] == number
                        and saved["compressed_bytes"]
                        == sum(r["bytes"] for r in saved["chunks"]),
                        "chunk checkpoint differs",
                    )
                    drive.reuse = saved["chunks"].copy()
                self.pack(drive, number, objects)
                codec.require(not drive.reuse, "old Drive chunk inventory not consumed")
                self.report(
                    new_drive_uploaded_bytes=drive.uploaded,
                    reused_drive_chunk_bytes=drive.reused_bytes,
                )
            measured = footprint([self.root])
            self.report(
                phase="drive-continuation-selected-inputs-complete",
                project_footprint=measured,
                mac_used_bytes=shutil.disk_usage(self.root).used,
                project_cap_met=measured["charged_bytes"] <= codec.PROJECT_CAP,
                mac_cap_met=shutil.disk_usage(self.root).used <= codec.MAC_CAP,
            )
            codec.atomic(self.work / "DRIVE_CONTINUATION_RESULT_2.json", self.progress)
        except BaseException as error:
            self.report(
                phase="drive-continuation-failed-preserving-unverified-originals",
                error_type=type(error).__name__,
                error=str(error),
            )
            codec.atomic(
                self.work
                / ("DRIVE_CONTINUATION_FAILED_2-" + str(time.time_ns()) + ".json"),
                self.progress,
            )
            raise
        finally:
            codec.atomic = original_atomic
            usage.update(closed=True, ended_unix=time.time())
            codec.atomic(ledger, usage)
            self.lease.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--amendment", type=Path, required=True)
    args = parser.parse_args()
    Continuation(args.root.resolve(), args.amendment).execute()
