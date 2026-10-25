"""Artifact-path, parser and immutable-read controls with no native execution."""

import argparse
import hashlib
import json
import os
import tempfile
from pathlib import Path

from verification.bundle import Bundle, strict_json


def rejected(action, reason):
    try:
        action()
    except (ValueError, OSError) as error:
        if reason is not None:
            assert reason in str(error), str(error)
        return str(error)
    raise AssertionError("invalid artifact was accepted")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    results = []
    for raw in ['{"value":1,"value":2}', '{"value":NaN}', '{"value":1e999}']:
        results.append(
            {
                "case": "strict-json",
                "input": raw,
                "reason": rejected(lambda: strict_json(raw), None),
            }
        )
    with tempfile.TemporaryDirectory(prefix="caissa-bundle-controls-") as temporary:
        root = Path(temporary)
        (root / "data.json").write_bytes(b'{"value":1}\n')
        identity = hashlib.sha256((root / "data.json").read_bytes()).hexdigest()
        manifest = {"files": {"data.json": identity}}
        (root / "MANIFEST.json").write_text(json.dumps(manifest))
        with Bundle(root, 10) as bundle:
            bundle.verify_manifest()
            assert bundle.json("data.json") == {"value": 1}
            (root / "data.json").write_bytes(b'{"value":2}\n')
            results.append(
                {
                    "case": "mutation-after-verification",
                    "reason": rejected(
                        lambda: bundle.json("data.json"), "changed after"
                    ),
                }
            )
            results.append(
                {
                    "case": "metadata-byte-ceiling",
                    "reason": rejected(
                        lambda: bundle.bytes("data.json", 4), "byte ceiling"
                    ),
                }
            )
            for name in [
                "../data.json",
                "/data.json",
                "a//data.json",
                "a/./data.json",
                "a\\data.json",
            ]:
                results.append(
                    {
                        "case": "unsafe-relative-path",
                        "path": name,
                        "reason": rejected(
                            lambda: bundle.bytes(name), "canonical relative"
                        ),
                    }
                )
        (root / "link").symlink_to(root / "data.json")
        with Bundle(root, 10) as bundle:
            results.append(
                {
                    "case": "linked-artifact",
                    "reason": rejected(bundle.verify_manifest, "symbolic link"),
                }
            )
        (root / "link").unlink()
        os.mkfifo(root / "pipe")
        with Bundle(root, 10) as bundle:
            results.append(
                {
                    "case": "nonregular-nonblocking-read",
                    "reason": rejected(lambda: bundle.bytes("pipe"), "regular file"),
                }
            )
        (root / "pipe").unlink()
        manifest["files"] = {"a//data.json": identity}
        (root / "MANIFEST.json").write_text(json.dumps(manifest))
        with Bundle(root, 10) as bundle:
            results.append(
                {
                    "case": "aliased-manifest-path",
                    "reason": rejected(bundle.verify_manifest, "canonical relative"),
                }
            )
    report = {
        "status": "passed",
        "cases": results,
        "scope": "Synthetic artifact integrity controls; no chess or model execution",
        "full_acceptance": False,
    }
    (args.output / "CONTROLS.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report))


if __name__ == "__main__":
    main()
