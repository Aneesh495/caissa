"""Unexecuted exact writer for the future seed or Bundle-control owner.

This supplies neither admission nor an owner. The real future owner must verify
the independent scope, own the host lease, install the process/directory guard,
prepay storage and descriptors, and independently close its actual execution.
"""

import os
from pathlib import Path
import stat
import threading

from tools.final_fixture_admission import ROOT, digest, relative, require
from tools.final_projection_bundle_controls import CASE_NAMES, FORGED_CASE_NAMES
from tools.parallel_storage_quota import Quota, RAW_OS_OPEN, ReservedFile, StorageLimit, UNIT


MAX_FILE_BYTES = 8 * 1024**2
INDEX_NAMES = {"decisions/" + gate + "/INDEX.json" for gate in ("G08", "G10", "G15")}
OWNER_FILES = {"OWNER_STARTED.json", "HELPER_RESULT.json", "OWNER_RESULT.json", "FAILED-owner.json"}


def writer_layout(scope):
    """Derive names from the admitted helper inputs, never from a pass flag."""
    operation, payload = scope["operation"], scope["payload"]
    require(operation in {"build-seed", "bundle-controls"}, "unsupported fixture writer operation")
    work = relative(scope["work"])
    require(work.startswith("work/") and len(work.split("/")) == 2,
            "fixture writer needs one direct admitted work namespace")
    immutable, mutable = set(OWNER_FILES), {}
    if operation == "build-seed":
        require(payload["seed"] == work + "/output/seed", "seed writer destination differs")
        names = payload["output_files"]
        require(isinstance(names, list) and 3 <= len(names) <= 1024
                and len(set(names)) == len(names), "exact bounded seed output names required")
        immutable.update("output/seed/" + relative(name) for name in names)
    else:
        require(payload["fixture"] == work + "/output/fixture"
                and payload["case_archive"] == work + "/output/cases",
                "control writer destinations differ")
        names = set(payload["seed_files"])
        require(3 <= len(names) <= 1024 and INDEX_NAMES <= names
                and {"MANIFEST.json", "FULL_INPUTS.json", "SOURCE_INPUTS.json"} <= names
                and not any(relative(name).split("/")[0].casefold() == "forgeries" for name in names),
                "seed writer inventory omits descriptors or occupies the forgery namespace")
        # One initial copy, twelve mutations and twelve restorations. Each of
        # three decision indexes changes in two cases, then restores twice.
        mutable = {"output/fixture/" + name: 5 for name in INDEX_NAMES}
        mutable.update({"output/fixture/" + name: 25
                        for name in ("MANIFEST.json", "FULL_INPUTS.json")})
        immutable.update("output/fixture/" + relative(name) for name in names
                         if "output/fixture/" + name not in mutable)
        immutable.update("output/fixture/FORGERIES/" + name + ".json" for name in FORGED_CASE_NAMES)
        immutable.update("output/cases/" + name + ".json"
                         for name in ("STARTED", "BASELINE", *CASE_NAMES))
    files = immutable | set(mutable)
    directories, aliases = set(), {}
    for name in files:
        parts = relative(name).split("/")
        for end in range(1, len(parts) + 1):
            prefix = "/".join(parts[:end])
            folded = prefix.casefold()
            require(folded not in aliases or aliases[folded] == prefix,
                    "fixture writer names alias on the case-insensitive filesystem")
            aliases[folded] = prefix
            if end < len(parts):
                require(prefix not in files, "fixture writer file also names a directory")
                directories.add(prefix)
    require(len(files) <= 1050 and len(directories) <= 4096,
            "fixture writer file or directory inventory exceeded")
    return frozenset(immutable), mutable, frozenset(directories)


def reservation_floor(scope):
    """Prepay every declared file cap, rounding and atomic control peak."""
    immutable, mutable, _ = writer_layout(scope)
    bounds = scope["writer_file_bounds"]
    require(isinstance(bounds, dict) and set(bounds) == immutable | set(mutable),
            "fixture file bounds omit or add a writer")
    for name, maximum in bounds.items():
        require(type(maximum) is int and 0 < maximum <= MAX_FILE_BYTES,
                "invalid separately admitted fixture file bound")
        if name in OWNER_FILES:
            require(maximum <= (1024**2 if name == "HELPER_RESULT.json" else 65536),
                    "owner metadata file bound exceeded")
    payload = scope["payload"]
    if scope["operation"] == "build-seed":
        for name, pin in payload["template_files"].items():
            if name not in {"MANIFEST.json", "FULL_INPUTS.json", "SOURCE_INPUTS.json"}:
                require(bounds["output/seed/" + name] >= pin["bytes"],
                        "seed copied input exceeds its prepaid file bound")
        for name, pin in payload["decision_records"].items():
            require(bounds["output/seed/decisions/retained/" + name] >= pin["bytes"],
                    "decision copy exceeds its prepaid file bound")
    else:
        for name, pin in payload["seed_files"].items():
            require(bounds["output/fixture/" + name] >= pin["bytes"],
                    "control seed input exceeds its prepaid file bound")
    data, control = 0, 0
    for name, maximum in bounds.items():
        rounded = ((maximum + UNIT - 1) // UNIT) * UNIT
        if name in mutable or name in OWNER_FILES or name.startswith("output/cases/"):
            control += 2 * rounded + 8192
        else:
            data += rounded + 8192
    require(type(scope["data_bytes"]) is int and scope["data_bytes"] >= data
            and type(scope["control_bytes"]) is int
            and type(scope["emergency_control_bytes"]) is int
            and scope["emergency_control_bytes"] > 0
            and scope["control_bytes"] >= control + scope["emergency_control_bytes"],
            "fixture file caps and rounded control peaks were not prepaid")
    return {"data_bytes": data, "control_bytes": control,
            "emergency_control_bytes": scope["emergency_control_bytes"], "file_count": len(bounds)}


class FixtureFile(ReservedFile):
    """Eight-MiB binary payloads, with credits before growth and no holes."""

    def __init__(self, quota, stream, kind, key, credit):
        super().__init__(quota, stream, kind, key, credit, True)
        self.high_water = 0

    def write(self, data):
        with self.lock:
            require(isinstance(data, (bytes, bytearray, memoryview)), "fixture writers require binary bytes")
            position = self.stream.tell()
            require(position <= self.high_water, "sparse fixture write rejected")
            end = position + memoryview(data).nbytes
            if end > self.quota.scope["writer_file_bounds"][self.key]:
                raise StorageLimit("individual fixture output size exhausted")
            if end > self.credit:
                extra = self.quota.reserve(self.kind, self.key,
                                          end - self.credit if self.kind == "data" else end)
                self.credit = self.credit + extra if self.kind == "data" else extra
            count = self.stream.write(data)
            self.high_water = max(self.high_water, self.stream.tell())
            return count

    def seek(self, offset, whence=os.SEEK_SET):
        with self.lock:
            before = self.stream.tell()
            position = self.stream.seek(offset, whence)
            if position > self.high_water:
                self.stream.seek(before)
                raise StorageLimit("sparse fixture seek rejected")
            return position

    def truncate(self, size=None):
        with self.lock:
            size = self.stream.tell() if size is None else size
            require(type(size) is int and 0 <= size <= self.high_water,
                    "fixture truncate growth rejected")
            result = self.stream.truncate(size)
            self.high_water = size
            return result


class FixtureQuota(Quota):
    """Separate fixture limits; accepted campaign quotas remain unchanged."""

    def __init__(self, scope, expected_scope_sha256):
        self.scope = scope
        self.immutable, self.mutable, self.directories = writer_layout(scope)
        self.reservation = reservation_floor(scope)
        require(scope["writer_reservation_floor"] == self.reservation,
                "fixture writer reservation differs from constructor readback")
        work = ROOT / relative(scope["work"])
        require(scope["schema"] == "caissa-final-fixture-owner-scope-v1"
                and scope["status"] == "admitted" and work == work.resolve(),
                "fixture quota requires a separately admitted owner scope")
        for key in ("data_bytes", "control_bytes", "emergency_control_bytes"):
            require(type(scope[key]) is int and scope[key] >= 0, "invalid fixture byte reservation")
        require(0 < scope["control_bytes"] <= 64000000
                and 0 < scope["emergency_control_bytes"] <= scope["control_bytes"]
                and scope["reserve_bytes"] == 128000000,
                "fixture control, emergency and reserve limits differ")
        super().__init__({"output": str(work), "ledger": str(work / "WRITE_USAGE.json"),
                          "scope_sha256": digest(expected_scope_sha256), "data_bytes": scope["data_bytes"],
                          "control_bytes": scope["control_bytes"],
                          "emergency_control_bytes": scope["emergency_control_bytes"],
                          "deadline_unix": scope["deadline_unix"], "reserve_bytes": 128000000})
        self.consumed = set()
        self.writer_lock = threading.RLock()

    def bind_helper(self, payload, expected_scope_sha256, operation):
        require(payload == self.scope["payload"] and self.scope["operation"] == operation
                and expected_scope_sha256 == self.spec["scope_sha256"],
                "helper payload differs from the separately admitted writer scope")

    def classify(self, target, *, replacement=False):
        target = Path(target).absolute()
        require(not replacement and target == target.resolve() and target.is_relative_to(self.output),
                "fixture replacement, linked or escaped destination rejected")
        name = str(target.relative_to(self.output))
        require(name in self.immutable or name in self.mutable, "undeclared fixture output")
        if target.exists():
            info = target.lstat()
            require(name in self.mutable and stat.S_ISREG(info.st_mode)
                    and info.st_nlink == 1 and stat.S_IMODE(info.st_mode) == 0o600,
                    "immutable, linked or public fixture output rejected")
        kind = "control" if name in self.mutable or name in OWNER_FILES or name.startswith("output/cases/") else "data"
        return kind, name

    def opener(self, original):
        fallback = super().opener(original)

        def open_file(file, mode="r", *args, **kwargs):
            if not any(flag in mode for flag in "wax+") or isinstance(file, int) or str(file) == os.devnull:
                return fallback(file, mode, *args, **kwargs)
            with self.writer_lock:
                kind, name = self.classify(file)
                require(mode in {"xb", "wb"} and "opener" not in kwargs,
                        "fixture writes require the owned binary opener")
                fresh = name not in self.consumed
                require(mode == ("xb" if fresh else "wb")
                        and (fresh or name in self.mutable), "fixture open mode or once-only path differs")
                if fresh:
                    self.consumed.add(name)

                def consume(state):
                    if name in self.mutable:
                        counts = state.setdefault("fixture_mutable_opens", {})
                        require(counts.get(name, 0) < self.mutable[name],
                                "fixture mutable open count exhausted")
                        counts[name] = counts.get(name, 0) + 1
                    state["fixture_writer_attempts"] = state.get("fixture_writer_attempts", 0) + 1

                self.update(consume)
                credit = self.reserve(kind, name, 0, initial=True)
                target = Path(file).absolute()

                def nofollow(actual, flags):
                    require(Path(actual).absolute() == target, "fixture opener target changed")
                    return RAW_OS_OPEN(actual, flags | os.O_NOFOLLOW, 0o600)

                stream = original(file, mode, *args, opener=nofollow, **kwargs)
                info = os.fstat(stream.fileno())
                if not (stat.S_ISREG(info.st_mode) and info.st_nlink == 1
                        and stat.S_IMODE(info.st_mode) == 0o600):
                    stream.close()
                    raise StorageLimit("fixture descriptor is linked, nonregular or public")
                return FixtureFile(self, stream, kind, name, credit)
        return open_file
