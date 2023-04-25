"""An inherited real file lock excludes competing timed and acceptance work."""

import fcntl
import os
from pathlib import Path

ENVIRONMENT = "CAISSA_HOST_LEASE_FD"


def inherited(path):
    raw = os.environ.get(ENVIRONMENT)
    if raw is None:
        return False
    if not raw.isascii() or not raw.isdecimal() or not 3 <= int(raw) <= 1048576:
        raise ValueError("invalid inherited host lease descriptor")
    descriptor = int(raw)
    actual, expected = os.fstat(descriptor), Path(path).stat()
    if (actual.st_dev, actual.st_ino) != (expected.st_dev, expected.st_ino):
        raise ValueError("inherited host lease refers to a different lock file")
    fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
    return True


class HostLease:
    def __init__(self, runs):
        self.path = Path(runs).resolve() / "TIMED_STRENGTH.lock"
        self.stream = self.path.open("a")
        try:
            fcntl.flock(self.stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BaseException:
            self.stream.close()
            raise ValueError("timed or acceptance work already owns the host")
        self.identity = self.path.stat()

    def check(self):
        actual = self.path.stat()
        if (actual.st_dev, actual.st_ino) != (
            self.identity.st_dev,
            self.identity.st_ino,
        ):
            raise ValueError("exclusive host lock was replaced")
        fcntl.flock(self.stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)

    def environment(self):
        return {**os.environ, ENVIRONMENT: str(self.stream.fileno())}

    def close(self):
        self.stream.close()
