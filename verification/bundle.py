"""Bounded, immutable artifact reads for independently supplied evidence.

Integrity is separate from domain verification. A valid manifest cannot certify
the scientific assertions made by the files it names.
"""

import hashlib
import json
import math
import os
import re
import stat
import time
from pathlib import Path

from verification.source import relative_path, require


def strict_json(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            require(key not in result, "duplicate JSON object key")
            result[key] = value
        return result

    def constant(value):
        raise ValueError("nonfinite JSON value: " + value)

    def number(value):
        result = float(value)
        require(math.isfinite(result), "nonfinite JSON number")
        return result

    return json.loads(
        raw, object_pairs_hook=pairs, parse_constant=constant, parse_float=number
    )


def digest_text(value):
    require(
        isinstance(value, str) and re.fullmatch("[0-9a-f]{64}", value),
        "artifact SHA256 is malformed",
    )
    return value


class Bundle:
    def __init__(self, root, maximum_seconds=600):
        require(
            math.isfinite(maximum_seconds) and 0 < maximum_seconds <= 3600,
            "finite evidence verification deadline required",
        )
        root = Path(root)
        require(
            root.is_dir() and not root.is_symlink(),
            "evidence root must be a real directory",
        )
        self.root = root.resolve()
        self.fd = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        self.monotonic_deadline = time.monotonic() + maximum_seconds
        self.wall_deadline = time.time() + maximum_seconds
        self.identities = None

    def __enter__(self):
        return self

    def __exit__(self, *_):
        os.close(self.fd)

    def tick(self):
        require(
            time.monotonic() < self.monotonic_deadline
            and time.time() < self.wall_deadline,
            "cumulative evidence verification deadline exhausted",
        )

    def open(self, name):
        parts = relative_path(name).split("/")
        self.tick()
        directory = os.dup(self.fd)
        try:
            for part in parts[:-1]:
                child = os.open(
                    part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory
                )
                os.close(directory)
                directory = child
            fd = os.open(
                parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory
            )
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode):
                os.close(fd)
                raise ValueError("evidence artifact must be a regular file")
            return os.fdopen(fd, "rb"), info
        finally:
            os.close(directory)

    def bytes(self, name, maximum_bytes=4 * 1024 * 1024):
        stream, before = self.open(name)
        with stream:
            require(
                0 <= before.st_size <= maximum_bytes,
                "evidence metadata byte ceiling exceeded",
            )
            raw = stream.read(maximum_bytes + 1)
            after = os.fstat(stream.fileno())
        require(
            len(raw) == before.st_size
            and len(raw) <= maximum_bytes
            and self.stamp(before) == self.stamp(after),
            "evidence metadata changed during read",
        )
        if self.identities is not None:
            require(
                name in self.identities
                and hashlib.sha256(raw).hexdigest() == self.identities[name],
                "verified metadata bytes changed after manifest validation",
            )
        self.tick()
        return raw

    @staticmethod
    def stamp(info):
        return (
            info.st_dev,
            info.st_ino,
            info.st_size,
            info.st_mtime_ns,
            info.st_ctime_ns,
        )

    def json(self, name, maximum_bytes=4 * 1024 * 1024):
        return strict_json(self.bytes(name, maximum_bytes))

    def sha(self, name, maximum_bytes=8 * 1024**3):
        stream, before = self.open(name)
        with stream:
            require(
                before.st_size <= maximum_bytes,
                "evidence artifact byte ceiling exceeded",
            )
            result = hashlib.sha256()
            size = 0
            while True:
                self.tick()
                block = stream.read(1048576)
                if not block:
                    break
                size += len(block)
                require(size <= maximum_bytes, "growing artifact exceeded byte ceiling")
                result.update(block)
            after = os.fstat(stream.fileno())
        require(
            size == before.st_size and self.stamp(before) == self.stamp(after),
            "evidence artifact changed during hashing",
        )
        return result.hexdigest()

    def names(self):
        names, total, directories = set(), 0, [self.root]
        while directories:
            self.tick()
            directory = directories.pop()
            with os.scandir(directory) as entries:
                for entry in entries:
                    self.tick()
                    require(not entry.is_symlink(), "evidence contains a symbolic link")
                    if entry.is_dir(follow_symlinks=False):
                        directories.append(Path(entry.path))
                        require(
                            len(directories) <= 10000,
                            "evidence directory ceiling exceeded",
                        )
                    else:
                        require(
                            entry.is_file(follow_symlinks=False),
                            "evidence contains a nonregular artifact",
                        )
                        name = relative_path(
                            str(Path(entry.path).relative_to(self.root))
                        )
                        names.add(name)
                        total += entry.stat(follow_symlinks=False).st_size
                        require(
                            len(names) <= 500000 and total <= 20 * 1024**3,
                            "evidence inventory resource ceiling exceeded",
                        )
        return names

    def verify_manifest(self, expected_manifest=None, excluded=()):
        if expected_manifest is not None:
            require(
                self.sha("MANIFEST.json", 64 * 1024 * 1024)
                == digest_text(expected_manifest),
                "evidence manifest differs from externally supplied identity",
            )
        manifest = self.json("MANIFEST.json", 64 * 1024 * 1024)
        require(isinstance(manifest, dict), "evidence manifest must be an object")
        identities = manifest.get("files")
        require(
            isinstance(identities, dict) and 0 < len(identities) <= 500000,
            "evidence manifest inventory is empty or excessive",
        )
        for name, digest in identities.items():
            relative_path(name)
            digest_text(digest)
        require(
            "MANIFEST.json" not in identities, "evidence manifest cannot hash itself"
        )
        actual = self.names() - {"MANIFEST.json", *excluded}
        require(set(identities) == actual, "artifact inventory mismatch")
        for name, digest in identities.items():
            require(self.sha(name) == digest, "artifact hash mismatch: " + name)
        self.identities = identities
        return identities

    def reference(self, record):
        require(
            isinstance(record, dict) and set(record) == {"path", "sha256"},
            "artifact reference must name an exact path and SHA256",
        )
        name = relative_path(record["path"])
        expected = digest_text(record["sha256"])
        require(
            self.identities is not None and self.identities.get(name) == expected,
            "referenced artifact differs from the verified manifest",
        )
        return name
