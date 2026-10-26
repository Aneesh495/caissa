"""Preserve and remove only observations beyond the committed checkpoint.

The checkpoint pointer is authoritative. A complete committed prefix is never
rewritten unless an uncommitted or torn tail follows it. Every removed byte is
durably retained before the journal is replaced.
"""

import hashlib
import json
import os
from pathlib import Path


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def durable(path, raw):
    temporary = path.with_suffix(path.suffix + ".recover.tmp")
    if temporary.exists() or temporary.is_symlink():
        if temporary.is_symlink() or not temporary.is_file():
            raise ValueError("unsafe recovery temporary file")
        temporary.unlink()
    with temporary.open("xb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)
    directory = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


def recover(folder, committed_step, checkpoint_every):
    if (
        type(committed_step) is not int
        or committed_step < 0
        or type(checkpoint_every) is not int
        or checkpoint_every < 1
    ):
        raise ValueError("invalid committed journal boundary")
    folder = Path(folder)
    path = folder / "observations.jsonl"
    if not path.exists():
        if committed_step:
            raise ValueError("committed checkpoint is missing its observation journal")
        return None
    if path.is_symlink() or path.stat().st_size > 16 * 1024**2:
        raise ValueError("observation journal exceeds safe recovery bounds")
    raw = path.read_bytes()
    offset = 0
    seen = set()
    for line in raw.splitlines(keepends=True):
        if not line.endswith(b"\n"):
            break
        try:
            row = json.loads(line)
        except (ValueError, UnicodeDecodeError):
            break
        if (
            not isinstance(row, dict)
            or type(row.get("step")) is not int
            or row["step"] <= 0
        ):
            raise ValueError("observation journal has an invalid step")
        if row["step"] > committed_step:
            break
        if row["step"] % checkpoint_every and row["step"] != committed_step:
            raise ValueError("observation journal differs from checkpoint cadence")
        seen.add(row["step"])
        offset += len(line)
    expected = set(range(checkpoint_every, committed_step + 1, checkpoint_every))
    if committed_step:
        expected.add(committed_step)
    if seen != expected:
        raise ValueError("recovery would discard or omit a committed observation")
    if offset == len(raw):
        return None
    prefix, tail = raw[:offset], raw[offset:]
    backups = folder / "recovery-tails"
    if backups.is_symlink():
        raise ValueError("unsafe recovery tail directory")
    backups.mkdir(exist_ok=True)
    if backups.is_symlink() or not backups.is_dir():
        raise ValueError("unsafe recovery tail directory")
    target = backups / (digest(tail) + ".bin")
    if target.exists():
        if target.is_symlink() or target.read_bytes() != tail:
            raise ValueError("preserved recovery tail identity differs")
    else:
        durable(target, tail)
    record = {
        "schema": "caissa-observation-recovery-v1",
        "committed_step": committed_step,
        "original_sha256": digest(raw),
        "preserved_prefix_sha256": digest(prefix),
        "discarded_tail_sha256": digest(tail),
        "preserved_prefix_bytes": len(prefix),
        "discarded_tail_bytes": len(tail),
        "tail": str(target.relative_to(folder)),
    }
    durable(folder / "RECOVERED_JOURNAL.json", (json.dumps(record) + "\n").encode())
    durable(path, prefix)
    return record
