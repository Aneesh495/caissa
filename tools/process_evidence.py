"""Publish host-load observations without process command lines or arguments."""

import argparse
import json
import os
from pathlib import Path


def public_snapshot(snapshot):
    """Keep measured host counters; allow no process strings except state."""
    result = {
        "unix": snapshot["unix"],
        "load": snapshot["load"],
        "process_arguments": "omitted",
    }
    for group in ("offenders", "top_processes"):
        result[group] = [
            {key: row[key] for key in ("pid", "ppid", "state", "cpu")}
            for row in snapshot[group]
        ]
    return result


def export(source, destination):
    """Create a separate sanitized JSONL copy; never overwrite original bytes."""
    source, destination = Path(source), Path(destination)
    if source.is_symlink() or not source.is_file():
        raise ValueError("host sample input must be a regular file")
    if source.stat().st_size > 32 * 1024 * 1024:
        raise ValueError("host sample input exceeds finite ceiling")
    count = 0
    # Exclusive creation also rejects existing files and destination symlinks.
    with (
        source.open(encoding="utf-8") as original,
        destination.open("x", encoding="utf-8") as output,
    ):
        for line in original:
            output.write(
                json.dumps(public_snapshot(json.loads(line)), separators=(",", ":"))
                + "\n"
            )
            count += 1
        output.flush()
        os.fsync(output.fileno())
    return count


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    count = export(args.source, args.destination)
    print(json.dumps({"records": count, "process_arguments": "omitted"}))


if __name__ == "__main__":
    main()
