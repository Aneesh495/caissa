"""Transport pieces for a later, separately admitted Drive continuation.

Importing this module starts no owner and grants no storage or experiment time.
"""

import hashlib
import json
import os
from pathlib import Path
import re
import time

from tools import storage_drive as previous

codec = previous.codec


class FailedUploadLatch:
    """Reject compression-finalizer re-entry after any failed upload."""

    def __init__(self, transfer):
        self.transfer = transfer
        self.failed = False

    def __call__(self, *args, **kwargs):
        codec.require(not self.failed, "upload failure latched; no retry admitted")
        try:
            return self.transfer(*args, **kwargs)
        except BaseException:
            self.failed = True
            raise


class ExactPrefix:
    """Reuse an exact checkpoint prefix, then allow later new chunks."""

    def __init__(self, prefix, rows):
        codec.require(re.fullmatch(r"[A-Za-z0-9._-]+", prefix), "unsafe pack prefix")
        self.prefix = prefix
        self.rows = [dict(row) for row in rows]
        self.position = 0
        for row in self.rows:
            codec.require(
                type(row["bytes"]) is int
                and 0 < row["bytes"] <= 33_554_432
                and re.fullmatch(r"[a-f0-9]{64}", row["sha256"])
                and re.fullmatch(r"[a-f0-9]{40}", row["git_blob"])
                and re.fullmatch(r"[A-Za-z0-9_-]+", row["drive_file_id"]),
                "invalid saved Drive chunk",
            )

    def take(self, data, name, objects):
        if self.position == len(self.rows):
            return None
        row = self.rows[self.position]
        expected_name = self.prefix + "-part-" + str(self.position).zfill(5) + ".bin"
        codec.require(
            name == expected_name
            and len(data) == row["bytes"]
            and hashlib.sha256(data).hexdigest() == row["sha256"]
            and codec.blob_oid(data) == row["git_blob"],
            "recompressed Drive prefix differs",
        )
        objects[row["git_blob"]] = dict(row)
        self.position += 1
        return row["git_blob"]


def private_json(path, value, *, replace=False):
    """Persist a private record before the caller consumes a bridge response."""
    path = Path(path)
    target = path.with_name(path.name + ".pending") if replace else path
    fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as stream:
        stream.write(codec.encoded(value))
        stream.flush()
        os.fsync(stream.fileno())
    if replace:
        os.replace(target, path)
    directory = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


class GuardedBridge(previous.Bridge):
    """Journal upload outcomes before response deletion and latch failures.

    Fetch URLs stay only in the existing private ephemeral bridge response.
    No download reference or raw provider error is copied to the journal.
    """

    def __init__(self, work, check):
        super().__init__(work, check)
        codec.require(
            not (self.directory / "REQUEST.json").exists(),
            "unresolved bridge request requires reconciliation",
        )
        self.counter = max(
            (
                int(path.name.split(".")[0])
                for path in self.directory.glob("*.controller.json")
                if re.fullmatch(r"\d{7}\.controller\.json", path.name)
            ),
            default=0,
        )
        self.upload = FailedUploadLatch(self._upload)

    def call(self, operation, **arguments):
        if operation == "upload":
            return self.upload(arguments)
        codec.require(operation == "fetch", "unsupported bridge operation")
        return self._call(operation, arguments, None)

    def _upload(self, arguments):
        codec.require(
            arguments["source_path"] == str(self.work / "drive-spool/upload.bin")
            and arguments["folder_id"] == previous.FOLDER
            and re.fullmatch(r"[A-Za-z0-9._-]+", arguments["file_name"])
            and type(arguments["expected_bytes"]) is int
            and 0 < arguments["expected_bytes"] <= 33_554_432
            and re.fullmatch(r"[a-f0-9]{64}", arguments["expected_sha256"]),
            "unsafe upload intent",
        )
        request_id = str(self.counter + 1).zfill(7)
        journal = self.work / ("DRIVE_UPLOAD_3-" + request_id + ".json")
        intent = {
            "schema": "caissa-drive-upload-outcome-v1",
            "request_id": request_id,
            "file_name": arguments["file_name"],
            "folder_id": arguments["folder_id"],
            "bytes": arguments["expected_bytes"],
            "sha256": arguments["expected_sha256"],
            "outcome": "pending",
            "observed_unix": time.time(),
        }
        private_json(journal, intent)
        return self._call("upload", arguments, (journal, intent))

    def _call(self, operation, arguments, upload):
        self.counter += 1
        request_id = str(self.counter).zfill(7)
        response = self.directory / (request_id + ".response.json")
        codec.require(not response.exists(), "bridge response already exists")
        request = self.directory / "REQUEST.json"
        codec.require(not request.exists(), "bridge request still pending")
        previous.private_json(
            request,
            {
                "schema": "caissa-drive-bridge-v1",
                "id": request_id,
                "operation": operation,
                **arguments,
            },
        )
        try:
            while True:
                self.check()
                if not response.exists():
                    time.sleep(0.25)
                    continue
                try:
                    result = json.loads(response.read_bytes())
                except json.JSONDecodeError:
                    time.sleep(0.1)
                    continue
                codec.require(
                    result.get("id") == request_id, "response identity differs"
                )
                if upload:
                    path, intent = upload
                    accepted = (
                        result.get("status") == "ok"
                        and type(result.get("bytes")) is int
                        and result["bytes"] == intent["bytes"]
                        and result.get("folder_id") == intent["folder_id"]
                        and result.get("private_owner_only") is True
                        and type(result.get("file_id")) is str
                        and len(result["file_id"]) <= 128
                        and re.fullmatch(r"[A-Za-z0-9_-]+", result["file_id"])
                    )
                    intent.update(
                        outcome="metadata-accepted" if accepted else "unknown",
                        observed_unix=time.time(),
                    )
                    if accepted:
                        intent["drive_file_id"] = result["file_id"]
                    private_json(path, intent, replace=True)
                    codec.require(accepted, "connected upload outcome unresolved")
                codec.require(result.get("status") == "ok", "connected transfer failed")
                request.unlink()
                response.unlink()
                return result
        except BaseException:
            if upload:
                path, intent = upload
                if intent["outcome"] == "pending":
                    intent.update(outcome="unknown", observed_unix=time.time())
                    private_json(path, intent, replace=True)
            # Retain unresolved REQUEST/response for explicit outcome reconciliation.
            raise
