"""Stream immutable evidence into small portable gzip volumes without relabeling it."""

import gzip
import hashlib
import json
import os
import stat
from pathlib import Path

CHUNK = 16 * 1024**2
MAXIMUM_INPUT = 8 * 1024**3


def stamp(value):
    return (
        value.st_dev,
        value.st_ino,
        value.st_size,
        value.st_mtime_ns,
        value.st_ctime_ns,
    )


def pack(source, destination, expected_sha256, expected_bytes, tick, progress=None):
    from verification.bundle import digest_text
    from verification.source import require

    digest_text(expected_sha256)
    require(
        type(expected_bytes) is int and 0 < expected_bytes <= MAXIMUM_INPUT,
        "portable input byte bound differs",
    )
    source, destination = Path(source), Path(destination)
    require(
        not destination.resolve().is_relative_to(source.resolve()),
        "portable destination overlaps input",
    )
    descriptor = os.open(source, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(descriptor, "rb") as original:
        before = os.fstat(original.fileno())
        require(
            stat.S_ISREG(before.st_mode) and before.st_size == expected_bytes,
            "portable input is linked, nonregular or has different size",
        )
        destination.mkdir(parents=True, exist_ok=False)
        volumes = destination / "volumes"
        volumes.mkdir()
        total, whole, records = 0, hashlib.sha256(), []
        while total < expected_bytes:
            tick()
            wanted = min(CHUNK, expected_bytes - total)
            path = volumes / f"{len(records):06d}.gz"
            raw_digest = hashlib.sha256()
            count = 0
            with path.open("xb") as stream:
                with gzip.GzipFile(
                    filename="", mode="wb", compresslevel=6, mtime=0, fileobj=stream
                ) as compressed:
                    while count < wanted:
                        tick()
                        block = original.read(min(1024**2, wanted - count))
                        require(
                            bool(block), "portable input ended before declared bytes"
                        )
                        count += len(block)
                        total += len(block)
                        whole.update(block)
                        raw_digest.update(block)
                        compressed.write(block)
                stream.flush()
                os.fsync(stream.fileno())
            compressed_digest = hashlib.sha256()
            compressed_bytes = 0
            with path.open("rb") as stream:
                for block in iter(lambda: stream.read(1024**2), b""):
                    tick()
                    compressed_digest.update(block)
                    compressed_bytes += len(block)
            require(
                0 < compressed_bytes <= wanted + 65536,
                "portable gzip volume exceeded its bound",
            )
            records.append(
                {
                    "path": f"volumes/{path.name}",
                    "raw_bytes": count,
                    "raw_sha256": raw_digest.hexdigest(),
                    "gzip_bytes": compressed_bytes,
                    "gzip_sha256": compressed_digest.hexdigest(),
                }
            )
            if progress is not None:
                progress(total, len(records))
        tick()
        require(
            original.read(1) == b""
            and not source.is_symlink()
            and stamp(before)
            == stamp(os.fstat(original.fileno()))
            == stamp(source.stat()),
            "portable original input changed during streaming",
        )
        require(
            whole.hexdigest() == expected_sha256, "portable original input SHA differs"
        )
    index = {
        "schema": "caissa-portable-evidence-volumes-v1",
        "raw_sha256": expected_sha256,
        "raw_bytes": expected_bytes,
        "chunk_bytes": CHUNK,
        "volumes": records,
        "semantic_verification_required": True,
    }
    raw = (json.dumps(index, sort_keys=True, separators=(",", ":")) + "\n").encode()
    with (destination / "VOLUMES.json").open("xb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    return {
        "index_sha256": hashlib.sha256(raw).hexdigest(),
        "raw_sha256": expected_sha256,
        "raw_bytes": total,
        "gzip_bytes": sum(r["gzip_bytes"] for r in records),
        "volumes": len(records),
        "semantic_verification_required": True,
    }


def main():
    # This entry point prepares bytes only. It is deliberately not a release
    # packager and cannot turn an archived failed experiment into a pass.
    from tools.portable_evidence import main as own

    own()


if __name__ == "__main__":
    main()
