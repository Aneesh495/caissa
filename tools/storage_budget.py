"""Enforce the user's project and whole-Mac storage limits before local growth."""

import os
from pathlib import Path
import shutil
import stat
import time

PROJECT_LIMIT = 5_000_000_000
MAC_LIMIT = 400_000_000_000


def footprint(paths):
    """Charge logical and allocated bytes, counting a hardlinked inode once.

    Project-owned caches outside the checkout must be passed explicitly. Shared
    system caches still count toward the whole-Mac limit through disk_usage.
    Directory symlinks are not followed to silently count another filesystem.
    """
    seen, logical, allocated, files = set(), 0, 0, 0
    pending = [Path(path).absolute() for path in paths]
    while pending:
        path = pending.pop()
        try:
            row = path.lstat()
        except FileNotFoundError:
            continue
        key = (row.st_dev, row.st_ino)
        if key in seen:
            continue
        seen.add(key)
        logical += row.st_size if not stat.S_ISDIR(row.st_mode) else 0
        allocated += getattr(row, "st_blocks", (row.st_size + 511) // 512) * 512
        if stat.S_ISDIR(row.st_mode):
            with os.scandir(path) as directory:
                pending.extend(Path(entry.path) for entry in directory)
        else:
            files += 1
    return {
        "logical_bytes": logical,
        "allocated_bytes": allocated,
        "charged_bytes": max(logical, allocated),
        "files": files,
    }


def admission(project_bytes, mac_bytes, expected_growth_bytes=0, reserve_bytes=0):
    values = (project_bytes, mac_bytes, expected_growth_bytes, reserve_bytes)
    if any(type(value) is not int or value < 0 for value in values):
        raise ValueError("invalid storage accounting value")
    additional = expected_growth_bytes + reserve_bytes
    if project_bytes + additional > PROJECT_LIMIT:
        raise ValueError("project5GB local storage limit would be exceeded")
    if mac_bytes + additional > MAC_LIMIT:
        raise ValueError("Mac400GB used storage limit would be exceeded")


class ProjectBudget:
    """Use before a producer starts and from its existing bounded guard.

    The caller must bound bytes emitted between checks below reserve_bytes.
    This guard does not grant new experiment starts, time, or disk allowances.
    """

    def __init__(self, root, external_project_paths=(), reserve_bytes=256_000_000):
        self.root = Path(root).resolve()
        self.paths = (self.root, *map(Path, external_project_paths))
        self.reserve_bytes = reserve_bytes
        self.last_check = None
        self.observation = None

    def check(self, expected_growth_bytes=0, force=False):
        now = time.monotonic()
        if (
            not force
            and expected_growth_bytes == 0
            and self.last_check is not None
            and now - self.last_check < 5
        ):
            return self.observation
        actual = footprint(self.paths)
        disk = shutil.disk_usage(self.root)
        admission(
            actual["charged_bytes"],
            disk.used,
            expected_growth_bytes,
            self.reserve_bytes,
        )
        actual.update(
            mac_used_bytes=disk.used,
            observed_unix=time.time(),
            project_limit_bytes=PROJECT_LIMIT,
            mac_limit_bytes=MAC_LIMIT,
            reserve_bytes=self.reserve_bytes,
        )
        self.observation = actual
        self.last_check = now
        return actual
