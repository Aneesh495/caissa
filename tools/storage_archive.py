"""Private, bounded, content-addressed archival with remote restore before eviction.

This is storage transport only. It neither reruns producers nor certifies gates.
Large payloads never enter the local Git object database or a local tar file.
"""

import argparse
import base64
import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import tarfile
import time

from tools.host_lease import HostLease

SCHEMA = "caissa-private-storage-archive-v1"
REPOSITORY = "Aneesh495/caissa-archive"
WORK = "work/storage-cap-migration-2026-10-27"
PROJECT_CAP = 5_000_000_000
MAC_CAP = 400_000_000_000
CHUNK = 32 * 1024 * 1024
PACK = 2_000_000_000
PARENT = 1793150297.974828


def require(condition, message):
    if not condition:
        raise ValueError(message)


def encoded(value):
    return json.dumps(value, separators=(",", ":"), sort_keys=True).encode() + b"\n"


def atomic(path, value):
    path = Path(path)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_bytes(encoded(value))
    os.replace(temporary, path)


def sha(path, check=lambda: None):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        while block := stream.read(4 * 1024 * 1024):
            check()
            digest.update(block)
    return digest.hexdigest()


def blob_oid(data):
    return hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()


def relative(value):
    path = Path(value)
    require(
        isinstance(value, str)
        and not path.is_absolute()
        and path.parts
        and ".." not in path.parts
        and str(path) == value,
        "unsafe archive path",
    )
    return path


class Github:
    def __init__(self, repository, check=lambda: None, interval=8.1):
        require(repository == REPOSITORY, "archive repository differs")
        self.repository, self.check, self.interval = repository, check, interval
        self.last_write = 0.0
        self.env = dict(os.environ)
        for name in ("GH_DEBUG", "GIT_TRACE", "GIT_CURL_VERBOSE"):
            self.env.pop(name, None)
        require(self.request("GET", "")["private"] is True, "archive must be private")

    def request(self, method, suffix, body=None, raw=False):
        self.check()
        command = ["gh", "api", "-X", method, "repos/" + self.repository + suffix]
        command += [
            "-H",
            (
                "Accept: application/vnd.github.raw+json"
                if raw
                else "Accept: application/vnd.github+json"
            ),
        ]
        payload = None if body is None else encoded(body)
        if payload is not None:
            command += ["--input", "-"]
        for attempt in range(3):
            self.check()
            if method != "GET":
                wait = self.interval - (time.monotonic() - self.last_write)
                if wait > 0:
                    time.sleep(wait)
                self.check()
                self.last_write = time.monotonic()
            result = subprocess.run(
                command, input=payload, capture_output=True, env=self.env, timeout=120
            )
            if result.returncode == 0:
                return result.stdout if raw else json.loads(result.stdout)
            # Never persist server stderr or credentials. The exit status and
            # operation are enough to identify a retry without process arguments.
            if attempt == 2:
                raise RuntimeError(
                    "GitHub archive request failed: "
                    + method
                    + " "
                    + suffix
                    + " exit "
                    + str(result.returncode)
                )
            time.sleep(8 * (attempt + 1))

    def put_blob(self, data):
        expected = blob_oid(data)
        response = self.request(
            "POST",
            "/git/blobs",
            {"encoding": "base64", "content": base64.b64encode(data).decode()},
        )
        require(response["sha"] == expected, "uploaded Git blob differs")
        actual = self.get_blob(expected)
        require(actual == data, "remote uploaded bytes differ")
        return expected

    def get_blob(self, oid):
        data = self.request("GET", "/git/blobs/" + oid, raw=True)
        require(blob_oid(data) == oid, "downloaded Git object differs")
        return data

    def commit(self, entries, message):
        require(self.request("GET", "")["private"] is True, "archive privacy changed")
        head = self.request("GET", "/git/ref/heads/main")["object"]["sha"]
        parent = self.request("GET", "/git/commits/" + head)
        tree = self.request(
            "POST", "/git/trees", {"base_tree": parent["tree"]["sha"], "tree": entries}
        )
        commit = self.request(
            "POST",
            "/git/commits",
            {"message": message + " [skip ci]", "tree": tree["sha"], "parents": [head]},
        )
        require(
            self.request("GET", "/git/ref/heads/main")["object"]["sha"] == head,
            "archive branch changed concurrently",
        )
        self.request(
            "PATCH", "/git/refs/heads/main", {"sha": commit["sha"], "force": False}
        )
        require(
            self.request("GET", "/git/ref/heads/main")["object"]["sha"]
            == commit["sha"],
            "archive commit not reachable",
        )
        inventory = self.request("GET", "/git/trees/" + tree["sha"] + "?recursive=1")
        require(inventory.get("truncated") is False, "archive tree inventory truncated")
        actual = {row["path"]: row for row in inventory["tree"]}
        for row in entries:
            require(
                actual.get(row["path"], {}).get("sha") == row["sha"],
                "archive tree binding differs",
            )
        return commit["sha"]


class ChunkWriter:
    def __init__(self, github, limit, on_chunk, chunk_bytes=CHUNK):
        self.github, self.limit, self.on_chunk = github, limit, on_chunk
        self.chunk_bytes, self.buffer, self.rows, self.size = (
            chunk_bytes,
            bytearray(),
            [],
            0,
        )

    def write(self, data):
        view = memoryview(data)
        while view:
            count = min(len(view), self.chunk_bytes - len(self.buffer))
            self.buffer.extend(view[:count])
            view = view[count:]
            if len(self.buffer) == self.chunk_bytes:
                self.flush_chunk()
        return len(data)

    def flush(self):
        pass

    def flush_chunk(self):
        if not self.buffer:
            return
        data = bytes(self.buffer)
        require(
            self.size + len(data) <= self.limit,
            "remote compressed byte ceiling exhausted",
        )
        oid = self.github.put_blob(data)
        row = {
            "bytes": len(data),
            "sha256": hashlib.sha256(data).hexdigest(),
            "git_blob": oid,
        }
        self.rows.append(row)
        self.size += len(data)
        self.buffer.clear()
        self.on_chunk(self.rows, self.size)


class ChunkReader:
    def __init__(self, github, rows):
        self.github, self.rows, self.index = github, rows, 0
        self.buffer, self.position = b"", 0

    def read(self, count=-1):
        require(count >= 0, "unbounded archive read prohibited")
        output = bytearray()
        while len(output) < count:
            if self.position == len(self.buffer):
                if self.index == len(self.rows):
                    break
                row = self.rows[self.index]
                self.buffer = self.github.get_blob(row["git_blob"])
                require(
                    len(self.buffer) == row["bytes"]
                    and hashlib.sha256(self.buffer).hexdigest() == row["sha256"],
                    "remote volume hash differs",
                )
                self.index += 1
                self.position = 0
            amount = min(count - len(output), len(self.buffer) - self.position)
            output.extend(self.buffer[self.position : self.position + amount])
            self.position += amount
        return bytes(output)


def verify_pack(github, manifest, destination=None, selected=None):
    require(manifest.get("schema") == SCHEMA, "archive manifest schema differs")
    expected = {row["sha256"]: row["bytes"] for row in manifest["objects"]}
    require(len(expected) == len(manifest["objects"]), "duplicate archive object")
    reader = ChunkReader(github, manifest["chunks"])
    seen = set()
    restored = False
    with gzip.GzipFile(fileobj=reader, mode="rb") as decoder:
        with tarfile.open(fileobj=decoder, mode="r|") as archive:
            for member in archive:
                prefix = "objects/"
                require(
                    member.isfile() and member.name.startswith(prefix),
                    "unexpected archive member",
                )
                pin = member.name[len(prefix) :]
                require(
                    pin in expected
                    and pin not in seen
                    and member.size == expected[pin],
                    "archive member inventory differs",
                )
                digest, size = hashlib.sha256(), 0
                stream = archive.extractfile(member)
                output = (
                    destination.open("xb")
                    if destination is not None and pin == selected
                    else None
                )
                try:
                    while data := stream.read(4 * 1024 * 1024):
                        digest.update(data)
                        size += len(data)
                        if output:
                            output.write(data)
                    if output:
                        output.flush()
                        os.fsync(output.fileno())
                        restored = True
                finally:
                    if output:
                        output.close()
                require(
                    digest.hexdigest() == pin and size == expected[pin],
                    "independent archive reconstruction differs",
                )
                seen.add(pin)
        while tail := decoder.read(1024 * 1024):
            require(not any(tail), "unexpected trailing archive payload")
    require(
        reader.index == len(reader.rows) and reader.position == len(reader.buffer),
        "archive has unread volumes",
    )
    require(seen == set(expected), "archive object missing")
    if destination is not None:
        require(
            restored and sha(destination) == selected, "requested object not restored"
        )
    return {
        "objects": len(seen),
        "raw_bytes": sum(expected.values()),
        "remote_reconstruction": "passed",
    }


def identity(path):
    row = path.lstat()
    require(stat.S_ISREG(row.st_mode), "archive input is not a regular file")
    return [
        row.st_size,
        stat.S_IMODE(row.st_mode),
        row.st_mtime_ns,
        row.st_dev,
        row.st_ino,
    ]


def keep_local(relative_path):
    parts = relative_path.parts
    if relative_path.is_symlink():
        return True
    if str(relative_path).startswith(WORK + "/"):
        return True
    if parts[:2] == ("runs", "full-parallel-strength-v1"):
        return True
    if parts[:2] == ("work", "parallel-bounded-continuation-2026-10-26"):
        return True
    if relative_path.name.endswith(".lock"):
        return True
    if parts[0] == "runs" and len(parts) == 3 and relative_path.suffix == ".json":
        return True
    if (
        parts[:2] == ("runs", "full-external-strength-v4")
        and len(parts) == 3
        and parts[-1] in {"STRENGTH_CAMPAIGN.json", "ACTIVE_USAGE.json"}
    ):
        return True
    # Source, dependencies, tracked proof and local control notes stay available.
    if parts[0] not in {"data", "runs", "work"} and not parts[0].startswith("build"):
        return True
    upper = relative_path.name.upper()
    if any(word in upper for word in ("HOST", "SECRET", "CREDENTIAL", "TOKEN", ".ENV")):
        return True
    return False


class Migration:
    def __init__(self, root, plan_path):
        self.root, self.plan_path = root.resolve(), plan_path.resolve()
        self.work = self.root / WORK
        self.plan = json.loads(self.plan_path.read_bytes())
        require(self.plan["schema"] == SCHEMA, "storage scope schema differs")
        require(self.plan["source_sha256"] == sha(__file__), "storage source changed")
        require(
            self.plan["parent_deadline_unix"] == PARENT
            and self.plan["deadline_unix"] <= PARENT,
            "storage parent deadline differs",
        )
        require(self.plan["repository"] == REPOSITORY, "storage repository differs")
        self.started = time.time()
        self.progress = {
            "phase": "admitting",
            "source_sha256": sha(__file__),
            "observed_unix": self.started,
        }
        self.check()

    def check(self):
        require(
            time.time() < self.plan["deadline_unix"],
            "storage migration deadline exhausted",
        )
        require(
            shutil.disk_usage(self.root).free >= self.plan["minimum_free_bytes"],
            "storage migration reserve exhausted",
        )
        if hasattr(self, "lease"):
            self.lease.check()

    def report(self, **fields):
        self.progress.update(fields, observed_unix=time.time())
        atomic(self.work / "ARCHIVE_PROGRESS.json", self.progress)

    def inventory(self):
        groups, files, total = {}, 0, 0
        path = self.work / "INVENTORY.jsonl"
        require(
            not path.exists(),
            "storage inventory already exists; use recorded continuation",
        )
        with path.open("xb") as output:
            for base in sorted(self.root.iterdir()):
                if not base.is_dir() or keep_local(base.relative_to(self.root)):
                    continue
                for directory, subdirs, names in os.walk(base, followlinks=False):
                    subdirs[:] = sorted(
                        name
                        for name in subdirs
                        if not keep_local(
                            (Path(directory) / name).relative_to(self.root)
                        )
                        and not (Path(directory) / name).is_symlink()
                    )
                    for name in sorted(names):
                        absolute = Path(directory) / name
                        rel = absolute.relative_to(self.root)
                        if keep_local(rel) or absolute.is_symlink():
                            continue
                        before = identity(absolute)
                        if before[1] == 0o600:
                            continue
                        pin = sha(absolute, self.check)
                        require(
                            identity(absolute) == before,
                            "storage input changed during inventory",
                        )
                        row = [str(rel), *before]
                        groups.setdefault(pin, []).append(row)
                        output.write(encoded([pin, *row]))
                        files += 1
                        total += before[0]
                        require(
                            files <= self.plan["maximum_files"]
                            and total <= self.plan["maximum_logical_input_bytes"],
                            "storage inventory ceiling exceeded",
                        )
                        require(
                            output.tell() <= self.plan["maximum_local_metadata_bytes"],
                            "storage metadata ceiling exceeded",
                        )
                        if files % 1000 == 0:
                            self.report(
                                phase="hashing-archive-inputs",
                                input_files=files,
                                logical_bytes=total,
                                unique_objects=len(groups),
                            )
        self.report(
            phase="inventory-complete",
            input_files=files,
            logical_bytes=total,
            unique_objects=len(groups),
            unique_bytes=sum(rows[0][1] for rows in groups.values()),
        )
        return groups

    def pack(self, github, number, objects, remaining):
        self.report(phase="uploading-pack", pack=number)
        folder = "packs/" + self.plan["archive_id"] + "/" + str(number).zfill(5)

        def checkpoint(rows, size):
            atomic(
                self.work / ("PACK-" + str(number).zfill(5) + "-UPLOADING.json"),
                {"chunks": rows, "compressed_bytes": size, "pack": number},
            )
            self.report(
                phase="uploading-pack",
                pack=number,
                current_pack_chunks=len(rows),
                current_pack_compressed_bytes=size,
            )

        sink = ChunkWriter(github, remaining, checkpoint)
        with gzip.GzipFile(
            fileobj=sink, mode="wb", compresslevel=3, mtime=0
        ) as compressor:
            with tarfile.open(
                fileobj=compressor, mode="w|", format=tarfile.USTAR_FORMAT
            ) as archive:
                for pin, rows in objects:
                    first = rows[0]
                    path = self.root / relative(first[0])
                    require(
                        identity(path) == first[1:],
                        "archive source changed before packing",
                    )
                    member = tarfile.TarInfo("objects/" + pin)
                    member.size, member.mode, member.mtime = first[1], 0o600, 0
                    with path.open("rb") as source:
                        archive.addfile(member, source)
                    require(
                        identity(path) == first[1:],
                        "archive source changed during packing",
                    )
        sink.flush_chunk()
        manifest = {
            "schema": SCHEMA,
            "archive_id": self.plan["archive_id"],
            "pack": number,
            "source_sha256": self.plan["source_sha256"],
            "chunks": sink.rows,
            "objects": [{"sha256": pin, "bytes": rows[0][1]} for pin, rows in objects],
            "paths": [[pin, *row] for pin, rows in objects for row in rows],
            "original_bytes_and_modes_preserved": True,
            "storage_transport_only": True,
            "full_acceptance": False,
        }
        raw = encoded(manifest)
        require(len(raw) <= 40_000_000, "archive pack manifest too large")
        manifest_oid = github.put_blob(raw)
        entries = [
            {
                "path": folder + "/manifest.json",
                "mode": "100644",
                "type": "blob",
                "sha": manifest_oid,
            }
        ]
        entries += [
            {
                "path": folder + "/part-" + str(i).zfill(5),
                "mode": "100644",
                "type": "blob",
                "sha": row["git_blob"],
            }
            for i, row in enumerate(sink.rows)
        ]
        commit = github.commit(
            entries, "Archive exact Caissa storage pack " + str(number)
        )
        self.report(
            phase="independently-reconstructing-remote-pack",
            pack=number,
            archive_commit=commit,
        )
        remote = github.get_blob(manifest_oid)
        require(remote == raw, "remote manifest differs")
        result = verify_pack(github, json.loads(remote))
        receipt = {
            "schema": SCHEMA,
            "pack": number,
            "manifest_git_blob": manifest_oid,
            "manifest_sha256": hashlib.sha256(raw).hexdigest(),
            "commit": commit,
            "repository": REPOSITORY,
            "result": result,
            "compressed_bytes": sink.size,
            "eviction_complete": False,
            "observed_unix": time.time(),
        }
        receipt_path = self.work / ("PACK-" + str(number).zfill(5) + "-VERIFIED.json")
        atomic(receipt_path, receipt)
        # Catalog is durable before any unlink. A crash leaves either local
        # originals or an exact, independently restored remote object.
        catalog = self.work / "RESTORE_CATALOG.jsonl"
        with catalog.open("ab") as output:
            for pin, rows in objects:
                for row in rows:
                    output.write(encoded([number, manifest_oid, commit, pin, *row]))
            output.flush()
            os.fsync(output.fileno())
        removed = 0
        for pin, rows in objects:
            for row in rows:
                self.check()
                path = self.root / relative(row[0])
                require(
                    identity(path) == row[1:], "local input changed before eviction"
                )
                require(
                    sha(path, self.check) == pin and identity(path) == row[1:],
                    "local input bytes changed before eviction",
                )
                path.unlink()
                removed += row[1]
        receipt.update(
            eviction_complete=True,
            removed_logical_bytes=removed,
            completed_unix=time.time(),
        )
        atomic(receipt_path, receipt)
        self.report(
            phase="pack-evicted-after-verified-remote-restore",
            pack=number,
            removed_logical_bytes=removed,
            compressed_bytes=sink.size,
        )
        return sink.size

    def execute(self):
        ledger = self.work / "ARCHIVE_USAGE.json"
        require(not ledger.exists(), "storage migration invocation already recorded")
        for name in ("full-parallel-strength-v1", "full-heuristics-strength-v1"):
            require(
                json.loads(
                    (self.root / "runs" / name / "ACTIVE_USAGE.json").read_bytes()
                ).get("closed")
                is True,
                "timed owner ledger is open",
            )
        self.lease = HostLease(self.root / "runs")
        atomic(
            ledger,
            {
                "started_unix": self.started,
                "source_sha256": self.plan["source_sha256"],
                "scope_sha256": sha(self.plan_path),
                "closed": False,
                "invocations_started": 1,
            },
        )
        try:
            github = Github(REPOSITORY, self.check)
            groups = self.inventory()
            packs, current, size = [], [], 0
            for pin, rows in sorted(
                groups.items(), key=lambda item: (-item[1][0][1], item[0])
            ):
                amount = rows[0][1]
                if current and size + amount > PACK:
                    packs.append(current)
                    current, size = [], 0
                current.append((pin, rows))
                size += amount
            if current:
                packs.append(current)
            total = 0
            for number, objects in enumerate(packs):
                total += self.pack(
                    github,
                    number,
                    objects,
                    self.plan["maximum_remote_compressed_bytes"] - total,
                )
            for base in self.root.iterdir():
                if base.is_dir() and not keep_local(base.relative_to(self.root)):
                    for directory, _, _ in os.walk(base, topdown=False):
                        try:
                            Path(directory).rmdir()
                        except OSError:
                            pass
            # du uses allocated bytes, including hard links once. Logical bytes
            # are also measured to prevent compressed/sparse files hiding growth.
            allocated = (
                int(subprocess.check_output(["du", "-sk", str(self.root)]).split()[0])
                * 1024
            )
            disk = shutil.disk_usage(self.root)
            self.report(
                phase="archive-migration-complete",
                packs=len(packs),
                remote_compressed_bytes=total,
                project_allocated_bytes=allocated,
                mac_used_bytes=disk.used,
                project_cap_met=allocated <= PROJECT_CAP,
                mac_cap_met=disk.used <= MAC_CAP,
            )
            atomic(self.work / "ARCHIVE_RESULT.json", self.progress)
        except BaseException as error:
            self.report(
                phase="failed-preserving-unverified-local-inputs",
                error_type=type(error).__name__,
                error=str(error),
            )
            atomic(
                self.work / ("ARCHIVE_FAILED-" + str(time.time_ns()) + ".json"),
                self.progress,
            )
            raise
        finally:
            atomic(
                ledger,
                {
                    "started_unix": self.started,
                    "ended_unix": time.time(),
                    "closed": True,
                    "source_sha256": self.plan["source_sha256"],
                    "scope_sha256": sha(self.plan_path),
                    "invocations_started": 1,
                },
            )
            self.lease.close()


def restore(root, value):
    root = root.resolve()
    target = root / relative(value)
    require(
        target.resolve().is_relative_to(root)
        and not any(parent.is_symlink() for parent in target.parents if parent != root),
        "restore parent is a symlink",
    )
    require(
        not target.exists() and not target.is_symlink(), "restore target already exists"
    )
    selected = []
    with (root / WORK / "RESTORE_CATALOG.jsonl").open("rb") as stream:
        for line in stream:
            row = json.loads(line)
            if row[4] == value:
                selected.append(row)
    require(len(selected) == 1, "restore catalog path absent or ambiguous")
    row = selected[0]
    allocated = int(subprocess.check_output(["du", "-sk", str(root)]).split()[0]) * 1024
    require(
        allocated + row[5] + 32 * 1024 * 1024 <= PROJECT_CAP,
        "restoration would exceed project5GB cap; use remote verification",
    )
    require(
        shutil.disk_usage(root).used + row[5] + 32 * 1024 * 1024 <= MAC_CAP,
        "restoration would exceed Mac400GB cap",
    )
    with_lease = HostLease(root / "runs")
    temporary = target.with_name(target.name + ".restoring")
    try:
        github = Github(REPOSITORY, with_lease.check)
        manifest = json.loads(github.get_blob(row[1]))
        require(
            row[3:] in manifest["paths"],
            "restore catalog differs from committed manifest",
        )
        target.parent.mkdir(parents=True, exist_ok=True)
        verify_pack(github, manifest, temporary, row[3])
        temporary.chmod(row[6])
        os.utime(temporary, ns=(row[7], row[7]))
        require(
            not target.exists() and not target.is_symlink(),
            "restore target appeared concurrently",
        )
        os.replace(temporary, target)
    finally:
        if temporary.exists():
            temporary.unlink()
        with_lease.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("migrate", "restore"))
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--plan", type=Path)
    parser.add_argument("--path")
    args = parser.parse_args()
    if args.mode == "migrate":
        require(args.plan is not None, "storage plan required")
        Migration(args.root, args.plan).execute()
    else:
        require(args.path is not None, "restore path required")
        restore(args.root, args.path)


if __name__ == "__main__":
    main()
