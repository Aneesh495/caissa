"""Separately admitted archival of untouched packs while pack 11 is unresolved."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time

from tools import storage_drive as previous
from tools import storage_drive_continuation as readback_policy
from tools import storage_drive_recovery as recovery
from tools.storage_budget import footprint

codec = previous.codec


def admit(root, amendment, *, require_preflight=True):
    """Read-only source/input admission; this function opens no usage ledger."""
    root = Path(root).resolve()
    work = root / previous.WORK
    plan_path = work / "DRIVE_ARCHIVE_SCOPE.json"
    plan = json.loads(plan_path.read_bytes())
    required_sources = {
        "tools/storage_drive.py",
        "tools/storage_drive_continuation.py",
        "tools/storage_drive_recovery.py",
        "tools/storage_drive_continuation_3.py",
        "tools/drive_controller_continuation_3.js",
        "tools/storage_archive.py",
        "tools/storage_archive_continuation.py",
        "tools/storage_budget.py",
        "tools/host_lease.py",
    }
    codec.require(
        required_sources <= amendment["source_pins"].keys(), "source binding incomplete"
    )
    codec.require(
        amendment["protected_files"].get("INVENTORY.jsonl")
        == "bf2262355de1824a5b811cfa4dae2821ac57cc7f52b94c3def616a2539fb28d8"
        and amendment["original_scope_sha256"]
        == "6eaf28fed46c2af9c1037a307aeb223eccbbb09fd11a8d64d2c27e6b6836b0e1"
        and amendment["python_executable"] == sys.executable
        and amendment["python_version"] == sys.version
        and amendment["python_binary_sha256"]
        == codec.sha(Path(sys.executable).resolve()),
        "inventory, original scope or canonical interpreter differs",
    )
    codec.require(
        amendment["system_curl_sha256"] == codec.sha(Path("/usr/bin/curl")),
        "system curl differs",
    )
    state = json.loads((root / ".agent-local/task.json").read_bytes())["storage_policy"]
    codec.require(
        state["drive_controller_cell_id"] is None
        and state["drive_controller_batches_started"]
        == amendment["controller_batches_previously_started"]
        < amendment["maximum_controller_batches"],
        "controller ownership or cumulative batch counter differs",
    )
    codec.require(
        amendment["parent_deadline_unix"] == codec.PARENT
        and amendment["original_deadline_unix"] == plan["deadline_unix"]
        and amendment["created_unix"] < amendment["deadline_unix"] <= codec.PARENT
        and amendment["deadline_unix"] - amendment["created_unix"] <= 10_800
        and amendment["extra_backend_starts"] == 1
        and amendment["maximum_controller_batches"]
        == plan["maximum_controller_batches"]
        and amendment["maximum_download_attempts_per_object"] == 3
        and amendment["selected_packs"] == list(range(12, 20))
        and amendment["deferred_packs"] == [11],
        "continuation3 finite selection or allowance differs",
    )
    for key in (
        "maximum_new_drive_bytes",
        "maximum_aggregate_remote_payload_bytes",
        "maximum_binary_chunk_bytes",
        "maximum_additional_local_staging_and_catalog_bytes",
        "minimum_free_bytes",
    ):
        codec.require(amendment[key] == plan[key], "old storage ceiling changed")
    codec.require(
        amendment["prior_confirmed_uploaded_bytes"] == 15_263_584_775
        and amendment["prior_uncertain_upload_reserved_bytes"] == 33_554_432
        and amendment["folder_id"] == previous.FOLDER
        and amendment["original_scope_sha256"] == codec.sha(plan_path),
        "continuation3 prior accounting or destination differs",
    )
    for relative, pin in amendment["source_pins"].items():
        codec.require(
            codec.sha(root / codec.relative(relative)) == pin, "source differs"
        )
    for relative, pin in amendment["protected_files"].items():
        codec.require(
            codec.sha(work / codec.relative(relative)) == pin, "old evidence differs"
        )
    prefix_path = work / codec.relative(amendment["catalog_prefix_file"])
    prefix = prefix_path.read_bytes()
    codec.require(
        len(prefix) == amendment["catalog_prefix_bytes"]
        and hashlib.sha256(prefix).hexdigest() == amendment["catalog_prefix_sha256"]
        and (work / "DRIVE_RESTORE_CATALOG.jsonl").read_bytes() == prefix,
        "initial Drive catalog prefix differs",
    )
    for name in ("DRIVE_ARCHIVE_USAGE.json", "DRIVE_CONTINUATION_USAGE_2.json"):
        codec.require(
            json.loads((work / name).read_bytes())["closed"], "old owner active"
        )
    for name in ("full-parallel-strength-v1", "full-heuristics-strength-v1"):
        codec.require(
            json.loads((root / "runs" / name / "ACTIVE_USAGE.json").read_bytes())[
                "closed"
            ],
            "chess owner active",
        )
    codec.require(
        not (work / "drive-bridge/REQUEST.json").exists()
        and not (work / "drive-bridge/CONTROLLER.lock").exists(),
        "unresolved bridge state",
    )
    for number in amendment["selected_packs"]:
        tail = "PACK-" + str(number).zfill(5)
        codec.require(
            not list(work.glob("*" + tail + "-UPLOADING.json"))
            and not list(work.glob("*" + tail + "-VERIFIED.json")),
            "selected pack has a prior outcome requiring reconciliation",
        )
    if require_preflight:
        codec.require(
            amendment["kind"] == "finite-drive-archive-continuation-3",
            "draft is not a start allowance",
        )
        path = work / codec.relative(amendment["preflight_result"])
        proof = json.loads(path.read_bytes())
        codec.require(
            codec.sha(path) == amendment["preflight_result_sha256"]
            and proof["passed"] is True
            and proof["source_pins"] == amendment["source_pins"]
            and proof["protected_files"] == amendment["protected_files"]
            and proof["selected_packs"] == amendment["selected_packs"]
            and proof["python_executable"] == amendment["python_executable"]
            and proof["provider_calls"] == 0,
            "canonical integration admission missing",
        )
        raw_path = work / codec.relative(proof["raw_result_file"])
        raw_proof = json.loads(raw_path.read_bytes())
        codec.require(
            proof["stderr_bytes"] == 0
            and codec.sha(raw_path) == proof["raw_result_sha256"]
            and raw_proof["passed"] is True
            and raw_proof["source_pins"] == amendment["source_pins"],
            "canonical integration result or diagnostics differ",
        )
    return plan


class Drive(previous.Drive):
    def __init__(self, owner):
        super().__init__(owner)
        self.bridge = recovery.GuardedBridge(owner.work, owner.check)
        self.uploaded = (
            owner.amendment["prior_confirmed_uploaded_bytes"]
            + owner.amendment["prior_uncertain_upload_reserved_bytes"]
        )
        self.put = recovery.FailedUploadLatch(self._put)

    def put_blob(self, data, name):
        return self.put(data, name)

    def _put(self, data, name):
        if name.endswith("-manifest.json.gz"):
            name = name.removesuffix(".json.gz") + "-continuation-3.json.gz"
        return super().put_blob(data, name)

    def get_blob(self, oid):
        row = self.objects[oid]
        for attempt in range(1, 4):
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
            remaining = self.owner.amendment["deadline_unix"] - time.time()
            codec.require(remaining > 1, "continuation3 deadline exhausted")
            timeout = min(120, remaining)
            fd = os.open(config, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "w") as stream:
                stream.write(
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
            try:
                self.owner.check()
                result = subprocess.run(
                    ["/usr/bin/curl", "--config", str(config)],
                    capture_output=True,
                    timeout=timeout + 5,
                )
                if result.returncode:
                    raw = result.stderr or b""
                    text = re.sub(
                        r"https?://\S+", "[URL omitted]", raw.decode("utf-8", "replace")
                    )
                    text = re.sub(
                        r"(?i)(authorization|cookie):[^\r\n]*", r"\1: [omitted]", text
                    )
                    part = destination.read_bytes() if destination.exists() else b""
                    recovery.private_json(
                        self.owner.work
                        / ("DRIVE_READBACK_3-" + str(time.time_ns()) + ".json"),
                        {
                            "file_id": row["drive_file_id"],
                            "attempt": attempt,
                            "curl_exit": result.returncode,
                            "expected_bytes": row["bytes"],
                            "partial_bytes": len(part),
                            "partial_sha256": hashlib.sha256(part).hexdigest(),
                            "sanitized_stderr": text[:2000],
                            "original_stderr_sha256": hashlib.sha256(raw).hexdigest(),
                        },
                    )
                    codec.require(
                        result.returncode in readback_policy.TRANSIENT_CURL
                        and attempt < 3,
                        "continuation3 readback failed, curl exit "
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
        raise ValueError("bounded continuation3 readback attempts exhausted")


class Continuation(previous.Migration):
    def __init__(self, root, amendment):
        self.root = Path(root).resolve()
        self.work = self.root / previous.WORK
        self.amendment_path = Path(amendment).resolve()
        self.amendment = json.loads(self.amendment_path.read_bytes())
        self.plan = admit(self.root, self.amendment)
        # A separately declared runtime view, with the original scope file unchanged.
        self.plan = {**self.plan, "deadline_unix": self.amendment["deadline_unix"]}
        self.progress = {
            "phase": "admitting-drive-continuation-3",
            "source_sha256": codec.sha(__file__),
            "amendment_sha256": codec.sha(self.amendment_path),
            "original_scope_sha256": self.amendment["original_scope_sha256"],
            "deferred_packs": [11],
            "project_storage_admission_completed": False,
        }
        self.last_work_measurement = None
        self.work_bytes = 0
        self.check()

    def check(self):
        codec.require(
            time.time() < self.amendment["deadline_unix"],
            "continuation3 fixed deadline exhausted",
        )
        disk = shutil.disk_usage(self.root)
        codec.require(
            disk.free >= self.plan["minimum_free_bytes"], "Drive disk reserve exhausted"
        )
        codec.require(disk.used <= codec.MAC_CAP, "Mac400GB cap exceeded")
        if hasattr(self, "lease"):
            self.lease.check()
        now = time.monotonic()
        if self.last_work_measurement is None or now - self.last_work_measurement >= 1:
            self.work_bytes = footprint([self.work])["charged_bytes"]
            self.last_work_measurement = now
        codec.require(
            self.work_bytes + 67_108_864
            <= self.plan["maximum_additional_local_staging_and_catalog_bytes"],
            "Drive bookkeeping/staging headroom exhausted",
        )

    def accounting(self):
        confirmed = self.amendment["prior_confirmed_uploaded_bytes"]
        reserved = self.amendment["prior_uncertain_upload_reserved_bytes"]
        for path in self.work.glob("DRIVE_UPLOAD_3-*.json"):
            row = json.loads(path.read_bytes())
            if row["outcome"] == "metadata-accepted":
                confirmed += row["bytes"]
            else:
                reserved += row["bytes"]
        return {
            "confirmed_drive_uploaded_bytes": confirmed,
            "uncertain_upload_reserved_bytes": reserved,
            "drive_ceiling_debit_bytes": confirmed + reserved,
        }

    def report(self, **values):
        values.pop("new_drive_uploaded_bytes", None)
        self.progress.update(values, **self.accounting(), observed_unix=time.time())
        recovery.private_json(
            self.work / "DRIVE_CONTINUATION_PROGRESS_3.json",
            self.progress,
            replace=(self.work / "DRIVE_CONTINUATION_PROGRESS_3.json").exists(),
        )

    def execute(self):
        ledger = self.work / "DRIVE_CONTINUATION_USAGE_3.json"
        codec.require(not ledger.exists(), "continuation3 start already consumed")
        codec.require(
            not list(self.work.glob("DRIVE_UPLOAD_3-*.json")),
            "old continuation3 intents exist",
        )
        self.lease = codec.HostLease(self.root / "runs")
        usage = {
            "closed": False,
            "started_unix": time.time(),
            "invocations_started": 1,
            "effective_drive_starts": 3,
            "effective_overall_storage_starts": 6,
            "amendment_sha256": codec.sha(self.amendment_path),
        }
        try:
            recovery.private_json(ledger, usage)
        except BaseException:
            self.lease.close()
            raise
        old_atomic = codec.atomic

        def separate_checkpoint(path, value):
            path = Path(path)
            if (
                path.parent == self.work
                and path.name.startswith("DRIVE_PACK-")
                and path.name.endswith("-UPLOADING.json")
            ):
                path = path.with_name("DRIVE_CONTINUATION_3_" + path.name)
            return old_atomic(path, value)

        codec.atomic = separate_checkpoint
        try:
            drive = Drive(self)
            for number, objects in enumerate(
                previous.grouping(self.work / "INVENTORY.jsonl")
            ):
                if number not in self.amendment["selected_packs"]:
                    continue
                self.check()
                # Bound the full catalog append before invoking the unchanged pack writer.
                catalog_growth = sum(
                    len(
                        codec.encoded(
                            {
                                "provider": "google-drive-private",
                                "path": row[0],
                                "sha256": pin,
                                "bytes": row[1],
                                "mode": row[2],
                                "mtime_ns": row[3],
                                "pack": number,
                                "manifest_file_id": "x" * 128,
                                "manifest_stored_bytes": 33_554_432,
                                "manifest_stored_sha256": "x" * 64,
                            }
                        )
                    )
                    for pin, rows in objects
                    for row in rows
                )
                current = footprint([self.work])["charged_bytes"]
                codec.require(
                    current + catalog_growth + 67_108_864
                    <= self.plan["maximum_additional_local_staging_and_catalog_bytes"],
                    "catalog append would exhaust staging allowance",
                )
                self.pack(drive, number, objects)
            self.report(
                phase="continuation3-selected-packs-complete-pack11-deferred",
                project_root_footprint=footprint([self.root]),
                project_cap_met=False,
            )
            prefix = (self.work / self.amendment["catalog_prefix_file"]).read_bytes()
            codec.require(
                (self.work / "DRIVE_RESTORE_CATALOG.jsonl")
                .read_bytes()
                .startswith(prefix),
                "old Drive catalog prefix changed",
            )
            recovery.private_json(
                self.work / "DRIVE_CONTINUATION_RESULT_3.json", self.progress
            )
        except BaseException as error:
            self.report(
                phase="continuation3-failed-preserving-originals",
                error_type=type(error).__name__,
                error=str(error),
            )
            recovery.private_json(
                self.work
                / ("DRIVE_CONTINUATION_FAILED_3-" + str(time.time_ns()) + ".json"),
                self.progress,
            )
            raise
        finally:
            codec.atomic = old_atomic
            usage.update(closed=True, ended_unix=time.time(), **self.accounting())
            try:
                recovery.private_json(ledger, usage, replace=True)
            finally:
                self.lease.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--amendment", type=Path, required=True)
    args = parser.parse_args()
    Continuation(args.root, args.amendment).execute()
