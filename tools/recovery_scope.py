"""Persistent ownership and resource limits for one recovery authorization."""

import fcntl
import json
import math
import shutil
import time
from pathlib import Path

from tools.campaign_process import atomic


def tree_bytes(path):
    total = 0
    for item in Path(path).rglob("*"):
        try:
            if item.is_file():
                total += item.stat().st_size
        except FileNotFoundError:
            # Atomic progress-file replacement may remove a discovered temp.
            continue
    return total


class RecoveryScope:
    def __init__(
        self,
        root,
        bindings,
        maximum_seconds,
        data_root,
        reserve_gib,
        additional_gib,
        *,
        resume=False,
        maximum_authorized_seconds=21600,
        maximum_active_seconds=None,
    ):
        self.root, self.data_root = Path(root), Path(data_root)
        self.root.mkdir(parents=True, exist_ok=resume)
        self.lock = (self.root / "OWNER.lock").open("a")
        fcntl.flock(self.lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        if (
            maximum_authorized_seconds not in (21600, 43200, 86400)
            or not math.isfinite(maximum_seconds)
            or not 0 < maximum_seconds <= maximum_authorized_seconds
        ):
            raise ValueError(
                "one finite deadline within the declared authorization is required"
            )
        self.start = time.monotonic()
        self.active_limit = maximum_active_seconds
        if self.active_limit is not None and (
            not math.isfinite(self.active_limit)
            or not 0 < self.active_limit <= maximum_seconds
        ):
            raise ValueError("finite cumulative active-time ceiling required")
        self.maximum_seconds = maximum_seconds
        self.reserve = reserve_gib * 1024**3
        self.additional = additional_gib * 1024**3
        path = self.root / "SCOPE.json"
        if path.exists():
            state = json.loads(path.read_text())
            if (
                state["bindings"] != bindings
                or state["maximum_seconds"] != maximum_seconds
                or state["minimum_free_bytes"] != self.reserve
                or state["maximum_additional_bytes"] != self.additional
                or state["data_root"] != str(self.data_root.resolve())
                or state.get("maximum_active_seconds") != self.active_limit
            ):
                raise ValueError("recovery resume inputs or cumulative limits changed")
            if state["deadline_unix"] != state["origin_unix"] + maximum_seconds:
                raise ValueError("recovery deadline record is inconsistent")
            if time.time() < state["origin_unix"] - 5:
                raise ValueError("wall clock precedes the original recovery origin")
            self.state = state
        else:
            if resume:
                raise ValueError("no original recovery deadline exists to resume")
            now = time.time()
            self.state = {
                "schema": "caissa-recovery-scope-v1",
                "bindings": bindings,
                "origin_unix": now,
                "deadline_unix": now + maximum_seconds,
                "maximum_seconds": maximum_seconds,
                "minimum_free_bytes": self.reserve,
                "maximum_additional_bytes": self.additional,
                "data_root": str(self.data_root.resolve()),
                "initial_data_bytes": tree_bytes(self.data_root),
            }
            if self.active_limit is not None:
                self.state["maximum_active_seconds"] = self.active_limit
            atomic(path, self.state)
        self.active_used = 0.0
        active_path = self.root / "ACTIVE_USAGE.json"
        if self.active_limit is not None and resume:
            if not active_path.exists():
                raise ValueError("cumulative active-time ledger missing")
            used = json.loads(active_path.read_text())
            if (
                used.get("maximum_active_seconds") != self.active_limit
                or type(used.get("active_seconds")) not in (int, float)
                or not math.isfinite(used["active_seconds"])
                or used["active_seconds"] < 0
                or type(used.get("closed")) is not bool
                or type(used.get("monotonic_stamp")) not in (int, float)
                or not math.isfinite(used["monotonic_stamp"])
            ):
                raise ValueError("cumulative active-time ledger is invalid")
            self.active_used = used["active_seconds"]
            if not used["closed"]:
                elapsed = self.start - used["monotonic_stamp"]
                if elapsed < 0:
                    raise ValueError(
                        "unclosed active-time ledger belongs to an earlier clock epoch"
                    )
                self.active_used += elapsed
        self.last_active_write = -math.inf
        self.deadline = self.state["deadline_unix"]
        self.monotonic_deadline = self.start + max(0, self.deadline - time.time())
        self.last_size_check = -math.inf
        self.check()

    def remaining(self):
        return min(
            self.deadline - time.time(),
            self.monotonic_deadline - time.monotonic(),
            (
                self.active_limit - self.active_used - (time.monotonic() - self.start)
                if self.active_limit is not None
                else math.inf
            ),
        )

    def check(self):
        if self.remaining() <= 0:
            raise TimeoutError("original cumulative recovery deadline exhausted")
        if shutil.disk_usage(self.root).free < self.reserve:
            raise ValueError("recovery disk reserve exhausted")
        if (
            self.active_limit is not None
            and time.monotonic() - self.last_active_write >= 1
        ):
            self._active_record(False)
        if time.monotonic() - self.last_size_check >= 5:
            size = (
                tree_bytes(self.root)
                + tree_bytes(self.data_root)
                - self.state["initial_data_bytes"]
            )
            if size > self.additional:
                raise ValueError("recovery additional disk ceiling exhausted")
            self.last_size_check = time.monotonic()

    def close(self):
        if self.active_limit is not None:
            self._active_record(True)
        self.lock.close()

    def _active_record(self, closed):
        now = time.monotonic()
        atomic(
            self.root / "ACTIVE_USAGE.json",
            {
                "maximum_active_seconds": self.active_limit,
                "active_seconds": self.active_used + now - self.start,
                "monotonic_stamp": now,
                "closed": closed,
            },
        )
        self.last_active_write = now
