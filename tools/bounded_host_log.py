"""Bound optional host observations without interrupting experiment work."""

import json
import os
import stat
import time
from pathlib import Path

from tools.campaign_process import atomic

LIMIT = 32 * 1024 * 1024
SATURATION = "host sample byte ceiling exhausted"


def omitted(output, retained_bytes):
    path = Path(output) / "HOST_SAMPLE_SATURATION.json"
    previous = json.loads(path.read_bytes()) if path.exists() else {}
    count = previous.get("omitted_snapshots", 0)
    if type(count) is not int or count < 0:
        count = 0
    atomic(
        path,
        {
            "schema": "caissa-host-log-saturation-v1",
            "limit_bytes": LIMIT,
            "retained_original_bytes": retained_bytes,
            "omitted_snapshots": count + 1,
            "last_omitted_unix": time.time(),
            "log_capacity_is_nonfatal": True,
            "original_bytes_preserved": True,
        },
    )


def append(output, snapshot):
    """Append already sanitized metadata, or retain a bounded omission counter."""
    path = Path(output) / "HOST_SAMPLES.jsonl"
    raw = (json.dumps(snapshot, separators=(",", ":")) + "\n").encode()
    descriptor = os.open(
        path, os.O_WRONLY | os.O_CREAT | os.O_APPEND | os.O_NOFOLLOW, 0o600
    )
    with os.fdopen(descriptor, "ab") as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode):
            raise ValueError("host observation destination is not a regular file")
        if info.st_size + len(raw) > LIMIT:
            omitted(output, info.st_size)
            return False
        stream.write(raw)
        stream.flush()
    return True


def archived_guard(base):
    """Retain every archived scope/power check and its five-second cadence."""

    class BoundedObservations(base):
        def check(self):
            try:
                return super().check()
            except ValueError as error:
                if str(error) != SATURATION:
                    raise
                # The original check already enforced scope, power and cadence.
                # Avoid a tight observer loop when the old file is saturated.
                self.last = time.monotonic()
                omitted(
                    self.output, (self.output / "HOST_SAMPLES.jsonl").stat().st_size
                )

    return BoundedObservations


def wall_scope(base, original_deadline, approved_deadline):
    """Expose an approved wall extension without changing original scope bytes."""
    if not original_deadline < approved_deadline <= 1793150297.974828:
        raise ValueError("wall-only continuation deadline is outside authorization")

    class AdditionalWall(base):
        @property
        def deadline(self):
            return approved_deadline

        @deadline.setter
        def deadline(self, original):
            if original != original_deadline:
                raise ValueError("original recovery deadline changed")

    return AdditionalWall
