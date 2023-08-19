"""Independently decode bounded gzip volumes against external original-byte pins."""

import argparse
import gzip
import hashlib
import json
import math
import os
import stat
import time
import zlib
from pathlib import Path

from verification.bundle import digest_text, strict_json
from verification.source import require


def identity(value):
    return (
        value.st_dev,
        value.st_ino,
        value.st_size,
        value.st_mtime_ns,
        value.st_ctime_ns,
    )


def regular(path, maximum):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    record = os.fstat(fd)
    if not stat.S_ISREG(record.st_mode) or not 0 < record.st_size <= maximum:
        os.close(fd)
        raise ValueError("portable member is not a bounded regular file")
    return os.fdopen(fd, "rb"), record


def reconstruct(
    index_path,
    index_sha256,
    original_sha256,
    original_bytes,
    output,
    maximum_seconds=600,
    tick=None,
):
    digest_text(index_sha256)
    digest_text(original_sha256)
    require(
        type(original_bytes) is int and 0 < original_bytes <= 8 * 1024**3,
        "external original byte ceiling differs",
    )
    require(
        type(maximum_seconds) in {int, float}
        and math.isfinite(maximum_seconds)
        and 0 < maximum_seconds <= 1800,
        "finite volume reconstruction deadline required",
    )
    begin, wall = time.monotonic(), time.time()

    def guard():
        require(
            time.monotonic() - begin < maximum_seconds
            and time.time() - wall < maximum_seconds,
            "original volume reconstruction deadline exhausted",
        )
        if tick is not None:
            tick()

    path, output = Path(index_path), Path(output)
    require(
        not path.parent.is_symlink() and not (path.parent / "volumes").is_symlink(),
        "portable volume directory is linked",
    )
    stream, before = regular(path, 1024**2)
    with stream:
        raw = stream.read(1024**2 + 1)
        require(
            identity(before) == identity(os.fstat(stream.fileno())),
            "portable index changed during read",
        )
    require(
        hashlib.sha256(raw).hexdigest() == index_sha256,
        "portable index differs from external identity",
    )
    index = strict_json(raw)
    require(
        isinstance(index, dict)
        and set(index)
        == {
            "schema",
            "raw_sha256",
            "raw_bytes",
            "chunk_bytes",
            "volumes",
            "semantic_verification_required",
        },
        "portable index field inventory differs",
    )
    require(
        index["schema"] == "caissa-portable-evidence-volumes-v1"
        and index["semantic_verification_required"] is True,
        "unsupported portable index schema or semantic promotion",
    )
    require(
        type(index["raw_bytes"]) is int
        and index["raw_bytes"] == original_bytes
        and index["raw_sha256"] == original_sha256,
        "portable original bytes differ from external identity",
    )
    require(
        type(index["chunk_bytes"]) is int and index["chunk_bytes"] == 16777216,
        "portable volume size contract differs",
    )
    rows = index["volumes"]
    require(
        isinstance(rows, list) and len(rows) == (original_bytes + 16777215) // 16777216,
        "portable volume count differs",
    )
    names = set()
    for number, row in enumerate(rows):
        require(
            isinstance(row, dict)
            and set(row)
            == {"path", "raw_bytes", "raw_sha256", "gzip_bytes", "gzip_sha256"},
            "portable volume inventory differs",
        )
        name = f"volumes/{number:06d}.gz"
        count = min(16777216, original_bytes - number * 16777216)
        require(
            row["path"] == name
            and type(row["raw_bytes"]) is int
            and row["raw_bytes"] == count
            and type(row["gzip_bytes"]) is int
            and 0 < row["gzip_bytes"] <= count + 65536,
            "portable volume order, path or byte limit differs",
        )
        digest_text(row["raw_sha256"])
        digest_text(row["gzip_sha256"])
        names.add(name)
    observed = set()
    for member in (path.parent / "volumes").iterdir():
        require(
            len(observed) < 512 and member.is_file() and not member.is_symlink(),
            "portable volume namespace differs",
        )
        observed.add("volumes/" + member.name)
    require(observed == names, "portable volumes are missing or extra")
    require(
        not output.exists()
        and not output.is_symlink()
        and not output.resolve().is_relative_to(path.parent.resolve()),
        "portable reconstruction must use a new external destination",
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    partial = output.with_name(output.name + ".partial")
    whole, total = hashlib.sha256(), 0
    with partial.open("xb") as destination:
        for row in rows:
            guard()
            stream, before = regular(
                path.parent / row["path"], row["raw_bytes"] + 65536
            )
            with stream:
                require(
                    before.st_size == row["gzip_bytes"],
                    "portable compressed member size differs",
                )
                compressed = hashlib.sha256()
                for block in iter(lambda: stream.read(1024**2), b""):
                    guard()
                    compressed.update(block)
                require(
                    compressed.hexdigest() == row["gzip_sha256"],
                    "portable compressed member SHA differs",
                )
                stream.seek(0)
                member_digest, member_bytes = hashlib.sha256(), 0
                with gzip.GzipFile(mode="rb", fileobj=stream) as decoded:
                    while True:
                        guard()
                        block = decoded.read(
                            min(1024**2, row["raw_bytes"] - member_bytes + 1)
                        )
                        if not block:
                            break
                        member_bytes += len(block)
                        require(
                            member_bytes <= row["raw_bytes"],
                            "portable decoded member exceeds its byte ceiling",
                        )
                        member_digest.update(block)
                        whole.update(block)
                        total += len(block)
                        destination.write(block)
                require(
                    identity(before) == identity(os.fstat(stream.fileno())),
                    "portable compressed member changed during decoding",
                )
                require(
                    member_bytes == row["raw_bytes"]
                    and member_digest.hexdigest() == row["raw_sha256"],
                    "portable decoded member SHA or length differs",
                )
        require(
            total == original_bytes and whole.hexdigest() == original_sha256,
            "portable reconstruction differs from original bytes",
        )
        destination.flush()
        os.fsync(destination.fileno())
    # Publish without replacing any concurrently created destination.
    os.link(partial, output)
    partial.unlink()
    fd = os.open(output.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)
    return {
        "status": "passed",
        "profile": "byte-reconstruction-only",
        "raw_sha256": whole.hexdigest(),
        "raw_bytes": total,
        "volumes": len(rows),
        "seconds": time.monotonic() - begin,
        "semantic_verification_required": True,
        "full_acceptance": False,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("index", type=Path)
    parser.add_argument("--expected-index-sha256", required=True)
    parser.add_argument("--expected-original-sha256", required=True)
    parser.add_argument("--expected-original-bytes", type=int, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--maximum-seconds", type=float, default=600)
    args = parser.parse_args()
    from tools.heuristic_study import avoid_decisive_matches
    from tools.host_lease import HostLease, inherited

    avoid_decisive_matches()
    lease = None
    try:
        if not inherited(Path("runs/TIMED_STRENGTH.lock")):
            lease = HostLease(Path("runs"))
        print(
            json.dumps(
                reconstruct(
                    args.index,
                    args.expected_index_sha256,
                    args.expected_original_sha256,
                    args.expected_original_bytes,
                    args.output,
                    args.maximum_seconds,
                    lease.check if lease else None,
                )
            )
        )
    except (ValueError, OSError, KeyError, EOFError, zlib.error) as error:
        print(
            json.dumps(
                {"status": "rejected", "reason": str(error), "full_acceptance": False}
            )
        )
        raise SystemExit(1)
    finally:
        if lease is not None:
            lease.close()


if __name__ == "__main__":
    main()
