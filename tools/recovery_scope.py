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
    ):
        self.root, self.data_root = Path(root), Path(data_root)
        self.root.mkdir(parents=True, exist_ok=resume)
        self.lock = (self.root / "OWNER.lock").open("a")
        fcntl.flock(self.lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        if (
            maximum_authorized_seconds not in (21600, 43200)
            or not math.isfinite(maximum_seconds)
            or not 0 < maximum_seconds <= maximum_authorized_seconds
        ):
            raise ValueError(
                "one finite deadline within the declared authorization is required"
            )
        self.start = time.monotonic()
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
            atomic(path, self.state)
        self.deadline = self.state["deadline_unix"]
        self.monotonic_deadline = self.start + max(0, self.deadline - time.time())
        self.last_size_check = -math.inf
        self.check()

    def remaining(self):
        return min(
            self.deadline - time.time(), self.monotonic_deadline - time.monotonic()
        )

    def check(self):
        if self.remaining() <= 0:
            raise TimeoutError("original cumulative recovery deadline exhausted")
        if shutil.disk_usage(self.root).free < self.reserve:
            raise ValueError("recovery disk reserve exhausted")
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
        self.lock.close()
