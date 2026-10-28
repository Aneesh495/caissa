"""Prospective byte reservations for the audited archived parallel writers.

This is a write boundary for this pinned Python campaign, not an OS sandbox.
Native actors use pipes and read-only inputs. Unknown regular-file descriptor
writes and destinations are rejected. No game record is changed on quota failure.
"""

import builtins
import fcntl
import io
import json
import os
from pathlib import Path
import re
import shutil
import stat
import threading
import time

RAW_OPEN = builtins.open
RAW_IO_OPEN = io.open
RAW_OS_OPEN = os.open
RAW_OS_WRITE = os.write
RAW_REPLACE = os.replace
RAW_RENAME = os.rename
UNIT = 65536


class StorageLimit(ValueError):
    pass


def check_admission(project, mac, data, control, reserve):
    values = (project, mac, data, control, reserve)
    if any(type(x) is not int or x < 0 for x in values):
        raise StorageLimit("invalid storage admission")
    if project + data + control + reserve > 5_000_000_000:
        raise StorageLimit("project5GB reservation rejected before owner admission")
    if mac + data + control + reserve > 400_000_000_000:
        raise StorageLimit("Mac400GB reservation rejected before owner admission")


class Quota:
    def __init__(self, spec):
        self.spec = spec
        self.output = Path(spec["output"]).resolve()
        self.ledger = Path(spec["ledger"]).resolve()
        self.mutex = threading.RLock()
        self.old = None

    def create(self):
        if self.ledger.exists():
            raise StorageLimit("storage session already exists; no reset")
        self.ledger.parent.mkdir(parents=True, exist_ok=True)
        state = {"data_used": 0, "control_used": 0, "control": {},
                 "scope_sha256": self.spec["scope_sha256"], "closed": False}
        with RAW_OPEN(self.ledger, "x") as stream:
            json.dump(state, stream, separators=(",", ":"))
            stream.flush()
            os.fsync(stream.fileno())
        self.ledger.chmod(0o600)

    def update(self, change):
        with self.mutex, RAW_OPEN(str(self.ledger) + ".lock", "a") as lock:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
            with RAW_OPEN(self.ledger) as stream:
                state = json.load(stream)
            if state["scope_sha256"] != self.spec["scope_sha256"]:
                raise StorageLimit("storage scope binding changed")
            if state.get("closed"):
                raise StorageLimit("storage session is closed")
            error = None
            try:
                change(state)
            except StorageLimit as caught:
                state["failure"] = str(caught)
                error = caught
            raw = json.dumps(state, separators=(",", ":")) + "\n"
            if len(raw.encode()) > 262144:
                raise StorageLimit("storage ledger metadata ceiling exhausted")
            temp = str(self.ledger) + ".tmp"
            with RAW_OPEN(temp, "w") as stream:
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
            RAW_REPLACE(temp, self.ledger)
            if error:
                raise error
            return state

    def read(self):
        with self.mutex, RAW_OPEN(str(self.ledger) + ".lock", "a") as lock:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
            with RAW_OPEN(self.ledger) as stream:
                return json.load(stream)

    def classify(self, path, *, replacement=False):
        path = Path(path).absolute()
        if path != path.resolve():
            raise StorageLimit("linked storage destination rejected")
        if not path.is_relative_to(self.output):
            raise StorageLimit("write outside the declared parallel output")
        relative = str(path.relative_to(self.output))
        canonical = path.with_suffix("") if path.suffix == ".tmp" else path
        data = re.fullmatch(
            r"matches/threads-[248]-ms-(?:100|400)/(?:games/0000\d{2}-[01]\.(?:json|pgn)|pairs/0000\d{2}\.json)(?:\.tmp)?",
            relative,
        )
        if data:
            if canonical.exists():
                raise StorageLimit("committed game/pair/PGN is immutable")
            return "data", relative
        if relative.startswith(("source/", "inputs/", "bin/")):
            raise StorageLimit("frozen source and inputs are read-only")
        if relative.startswith("attempts/") and not relative.startswith("attempts/attempt-005/"):
            raise StorageLimit("old attempt evidence is read-only")
        if relative.startswith("matches/"):
            if not re.fullmatch(r"matches/threads-[248]-ms-(?:100|400)/(?:CONFIG|PROTOCOL|SUMMARY)\.json(?:\.tmp)?", relative):
                raise StorageLimit("unknown match output")
        elif "/" in relative and not relative.startswith("attempts/attempt-005/"):
            raise StorageLimit("unknown parallel output directory")
        if not re.fullmatch(r"[A-Za-z0-9_./-]{1,180}", relative):
            raise StorageLimit("invalid output path")
        if canonical.name in self.spec.get("immutable_root_names", []):
            raise StorageLimit("old scope/failure record is immutable")
        return "control", relative

    def reserve(self, kind, key, amount, *, initial=False):
        rounded = ((max(1, amount) + UNIT - 1) // UNIT) * UNIT

        def change(state):
            emergency = kind == "control" and (key.endswith(("ACTIVE_USAGE.json.tmp", "CAMPAIGN.json.tmp", "COMMANDS.jsonl")) or key.startswith("FAILED-"))
            if time.time() >= self.spec["deadline_unix"] and not emergency:
                raise StorageLimit("storage session deadline exhausted")
            if shutil.disk_usage(self.output).used + self.spec["reserve_bytes"] > 400_000_000_000:
                raise StorageLimit("actual whole-Mac used ceiling exhausted")
            if kind == "data":
                if state.get("failure"):
                    raise StorageLimit("authoritative storage failure latched")
                debit = rounded + (8192 if initial else 0)
                if state["data_used"] + debit > self.spec["data_bytes"]:
                    raise StorageLimit("authoritative output byte allowance exhausted")
                state["data_used"] += debit
            else:
                previous = state["control"].get(key, 0)
                wanted = max(previous, rounded)
                debit = 2 * (wanted - previous) + (8192 if key not in state["control"] else 0)
                if len(state["control"]) >= 512 and key not in state["control"]:
                    raise StorageLimit("control path count exhausted")
                ceiling = self.spec["control_bytes"] - (0 if emergency else self.spec.get("emergency_control_bytes", 0))
                if state["control_used"] + debit > ceiling:
                    raise StorageLimit("control/log peak byte allowance exhausted")
                state["control"][key] = wanted
                state["control_used"] += debit
        self.update(change)
        return rounded

    def opener(self, original):
        def open_file(file, mode="r", *args, **kwargs):
            writing = any(flag in mode for flag in "wax+")
            if not writing:
                return original(file, mode, *args, **kwargs)
            if isinstance(file, int):
                if stat.S_ISREG(os.fstat(file).st_mode):
                    raise StorageLimit("untracked regular descriptor write")
                return original(file, mode, *args, **kwargs)
            if str(file) == os.devnull:
                return original(file, mode, *args, **kwargs)
            kind, key = self.classify(file)
            size = Path(file).stat().st_size if Path(file).exists() else 0
            credit = self.reserve(kind, key, size if "a" in mode else 0, initial=True)
            stream = original(file, mode, *args, **kwargs)
            return ReservedFile(self, stream, kind, key, credit, "b" in mode)
        return open_file

    def install(self):
        if self.old is not None:
            raise StorageLimit("quota already installed")
        self.old = (builtins.open, io.open, os.open, os.write, os.replace, os.rename)
        builtins.open = self.opener(RAW_OPEN)
        io.open = self.opener(RAW_IO_OPEN)

        def raw_open(path, flags, *args, **kwargs):
            if flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC):
                if str(path) != os.devnull:
                    raise StorageLimit("raw regular-file write bypass rejected")
            return RAW_OS_OPEN(path, flags, *args, **kwargs)

        def move(original):
            def replace(source, target, *args, **kwargs):
                self.classify(source)
                self.classify(target, replacement=True)
                return original(source, target, *args, **kwargs)
            return replace
        def raw_write(descriptor, data):
            if stat.S_ISREG(os.fstat(descriptor).st_mode):
                raise StorageLimit("raw descriptor write bypass rejected")
            return RAW_OS_WRITE(descriptor, data)
        os.write = raw_write
        os.open, os.replace, os.rename = raw_open, move(RAW_REPLACE), move(RAW_RENAME)

    def uninstall(self):
        if self.old is not None:
            builtins.open, io.open, os.open, os.write, os.replace, os.rename = self.old
            self.old = None


class ReservedFile:
    def __init__(self, quota, stream, kind, key, credit, binary):
        self.quota, self.stream, self.kind, self.key = quota, stream, kind, key
        self.credit, self.binary = credit, binary
        self.lock = threading.RLock()

    def write(self, data):
        with self.lock:
            size = len(data) if self.binary else len(data.encode(self.stream.encoding or "utf-8"))
            end = self.stream.tell() + size
            maximum = 4 * 1024**2 if self.kind == "data" else 40 * 1024**2
            if end > maximum:
                raise StorageLimit("individual output size exhausted")
            if end > self.credit:
                extra = self.quota.reserve(self.kind, self.key, end - self.credit if self.kind == "data" else end)
                self.credit = self.credit + extra if self.kind == "data" else extra
            return self.stream.write(data)

    def writelines(self, lines):
        for line in lines:
            self.write(line)

    def truncate(self, size=None):
        size = self.stream.tell() if size is None else size
        if size > self.stream.tell() or size > self.credit:
            raise StorageLimit("sparse/truncate growth rejected")
        return self.stream.truncate(size)

    @property
    def buffer(self):
        raise StorageLimit("raw buffer bypass rejected")

    @property
    def raw(self):
        raise StorageLimit("raw stream bypass rejected")

    def detach(self):
        raise StorageLimit("detached stream bypass rejected")

    def __getattr__(self, name):
        return getattr(self.stream, name)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return self.stream.__exit__(*args)
