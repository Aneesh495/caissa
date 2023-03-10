"""Actual bounded-memory copies and immutable-read/overwrite rejection controls."""

import argparse
import hashlib
import json
import tempfile
import time
import tracemalloc
from pathlib import Path

from tests.bundle_integrity import rejected
from verification.bundle import Bundle


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    cases = []
    with tempfile.TemporaryDirectory(prefix="caissa-stream-copy-") as temporary:
        root = Path(temporary) / "evidence"
        root.mkdir()
        payload = b"original-evidence\n" * 524288
        source = root / "raw.bin"
        source.write_bytes(payload)
        sha = hashlib.sha256(payload).hexdigest()
        (root / "MANIFEST.json").write_text(json.dumps({"files": {"raw.bin": sha}}))
        destination = Path(temporary) / "copy.bin"
        with Bundle(root, 20) as bundle:
            bundle.verify_manifest()
            tracemalloc.start()
            copied = bundle.copy("raw.bin", destination, 16 * 1024**2)
            _, peak = tracemalloc.get_traced_memory()
            tracemalloc.stop()
            assert copied == {"bytes": len(payload), "sha256": sha}
            assert peak < 4 * 1024**2, peak
            assert destination.read_bytes() == payload
            cases.append(
                {
                    "case": "actual-stream-copy",
                    "bytes": len(payload),
                    "peak_python_bytes": peak,
                }
            )
            cases.append(
                {
                    "case": "no-overwrite",
                    "reason": rejected(
                        lambda: bundle.copy("raw.bin", destination), None
                    ),
                }
            )
            assert destination.read_bytes() == payload
            cases.append(
                {
                    "case": "preserve-original-root",
                    "reason": rejected(
                        lambda: bundle.copy("raw.bin", root / "extra.bin"),
                        "preserve the original",
                    ),
                }
            )
            cases.append(
                {
                    "case": "copy-byte-ceiling",
                    "reason": rejected(
                        lambda: bundle.copy(
                            "raw.bin", Path(temporary) / "too-large", 1024
                        ),
                        "byte ceiling",
                    ),
                }
            )
            cases.append(
                {
                    "case": "typed-byte-ceiling",
                    "reason": rejected(
                        lambda: bundle.copy(
                            "raw.bin", Path(temporary) / "bool-bound", True
                        ),
                        "byte ceiling",
                    ),
                }
            )
            source.write_bytes(b"changed evidence\n")
            cases.append(
                {
                    "case": "changed-after-manifest",
                    "reason": rejected(
                        lambda: bundle.copy("raw.bin", Path(temporary) / "changed"),
                        "changed after manifest",
                    ),
                }
            )
            source.unlink()
            source.symlink_to(destination)
            cases.append(
                {
                    "case": "linked-source",
                    "reason": rejected(
                        lambda: bundle.copy("raw.bin", Path(temporary) / "linked"), None
                    ),
                }
            )
        source.unlink()
        source.write_bytes(payload)
        with Bundle(root, 20) as bundle:
            cases.append(
                {
                    "case": "unverified-source",
                    "reason": rejected(
                        lambda: bundle.copy("raw.bin", Path(temporary) / "unverified"),
                        "verified manifest",
                    ),
                }
            )
            bundle.verify_manifest()
            bundle.wall_deadline = time.time() - 1
            cases.append(
                {
                    "case": "original-deadline",
                    "reason": rejected(
                        lambda: bundle.copy("raw.bin", Path(temporary) / "expired"),
                        "deadline exhausted",
                    ),
                }
            )
    value = {
        "status": "passed",
        "cases": cases,
        "full_acceptance": False,
        "scope": "Synthetic immutable streaming-copy controls; no model/native execution",
    }
    (args.output / "CONTROLS.json").write_text(json.dumps(value, indent=2) + "\n")
    print(json.dumps(value))


if __name__ == "__main__":
    main()
