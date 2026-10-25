"""Crash-safe independent reconstruction transactions and immutable bindings."""

import fcntl
import hashlib
import json
import sqlite3
import tempfile
import time
from pathlib import Path

from verification.protocol import read_json


def snapshot(directory, check=None):
    """Fingerprint a stopped index for an externally retained resume pin."""
    deadline = time.time() + 60
    result = hashlib.sha256(b"caissa-independent-index-state-v1\0")
    for name in ("replayed.sqlite3", "replayed.sqlite3-wal"):
        path = Path(directory) / name
        if path.exists():
            if path.is_symlink() or not 0 <= path.stat().st_size <= 20 * 1024**3:
                raise ValueError("independent index snapshot size or link is invalid")
            result.update(
                name.encode() + b"\0" + path.stat().st_size.to_bytes(8, "little")
            )
            with path.open("rb") as stream:
                for block in iter(lambda: stream.read(1024 * 1024), b""):
                    if time.time() > deadline:
                        raise TimeoutError("independent index snapshot deadline")
                    if check is not None:
                        check()
                    result.update(block)
        else:
            result.update(name.encode() + b"\0absent")
    return result.hexdigest()


class ReplayIndex:
    def __init__(self, scratch, retain, bindings, resume=None, expected_snapshot=None):
        self.temporary = None
        if resume is None:
            self.temporary = tempfile.TemporaryDirectory(
                prefix="caissa-verify-data-", dir=scratch, delete=not retain
            )
            self.directory = Path(self.temporary.name)
        else:
            self.directory = Path(resume)
            if (
                not self.directory.is_dir()
                or not (self.directory / "replayed.sqlite3").is_file()
            ):
                raise ValueError("independent resume index is missing")
        self.lock = (self.directory / "OWNER.lock").open("a")
        fcntl.flock(self.lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        if resume is not None and (
            expected_snapshot is None or snapshot(self.directory) != expected_snapshot
        ):
            self.lock.close()
            raise ValueError(
                "independent index differs from externally pinned stopped checkpoint"
            )
        self.connection = sqlite3.connect(
            self.directory / "replayed.sqlite3", timeout=1
        )
        self.bindings = bindings
        try:
            if resume is None:
                self.connection.execute("PRAGMA journal_mode=WAL")
                self.connection.execute("PRAGMA synchronous=FULL")
                self.connection.execute("PRAGMA wal_autocheckpoint=4096")
                self.connection.execute(
                    "CREATE TABLE expected (id BLOB PRIMARY KEY,split INTEGER,fen TEXT,outcome REAL,cp REAL,probability REAL,n INTEGER,game TEXT,family TEXT) WITHOUT ROWID"
                )
                self.connection.execute(
                    "CREATE TABLE contributors (id BLOB,game TEXT,n INTEGER,first INTEGER,last INTEGER,PRIMARY KEY(id,game)) WITHOUT ROWID"
                )
                self.connection.execute(
                    "CREATE TABLE replay_checkpoint (singleton INTEGER PRIMARY KEY CHECK(singleton=1),bindings TEXT NOT NULL,state TEXT NOT NULL)"
                )
                self.state = {
                    "cursor": 0,
                    "complete_games": 0,
                    "unfinished_games": 0,
                    "raw_samples": 0,
                    "searched_samples": 0,
                    "prefix_sha256": None,
                }
                self.commit(self.state)
            else:
                # Opening a WAL database recovers its last committed state. An
                # old journal-OFF scratch index has no certified cursor and is
                # deliberately not eligible for this continuation protocol.
                try:
                    row = self.connection.execute(
                        "SELECT bindings,state FROM replay_checkpoint WHERE singleton=1"
                    ).fetchone()
                except sqlite3.DatabaseError as error:
                    raise ValueError(
                        "independent index lacks a valid atomic replay checkpoint"
                    ) from error
                if row is None or read_json(row[0]) != bindings:
                    raise ValueError(
                        "independent replay checkpoint source/data bindings changed"
                    )
                self.state = read_json(row[1])
                if set(self.state) != {
                    "cursor",
                    "complete_games",
                    "unfinished_games",
                    "raw_samples",
                    "searched_samples",
                    "prefix_sha256",
                } or any(
                    type(self.state[key]) is not int or self.state[key] < 0
                    for key in self.state
                    if key != "prefix_sha256"
                ):
                    raise ValueError(
                        "independent replay checkpoint counters are invalid"
                    )
                if (
                    self.connection.execute("PRAGMA journal_mode").fetchone()[0]
                    != "wal"
                ):
                    raise ValueError("independent replay index has no crash-safe WAL")
                self.connection.execute("PRAGMA synchronous=FULL")
                self.connection.execute("PRAGMA wal_autocheckpoint=4096")
            self.connection.execute("PRAGMA cache_size=-131072")
        except BaseException:
            self.connection.close()
            self.lock.close()
            if self.temporary is not None:
                self.temporary.cleanup()
            raise

    def commit(self, state):
        # Expected inputs, contributors, cursor, counters and prefix identity
        # enter the same SQLite commit. An interrupted batch is never trusted.
        self.connection.execute(
            "INSERT INTO replay_checkpoint VALUES(1,?,?) ON CONFLICT(singleton) DO UPDATE SET state=excluded.state",
            (
                json.dumps(self.bindings, sort_keys=True, separators=(",", ":")),
                json.dumps(state, sort_keys=True, separators=(",", ":")),
            ),
        )
        self.connection.commit()
        self.state = dict(state)

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.connection.close()
        self.lock.close()
        if self.temporary is not None:
            self.temporary.cleanup()
