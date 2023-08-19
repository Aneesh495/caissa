"""Real streamed byte reconstruction and rehashed malformed archive controls."""

import argparse
import gzip
import hashlib
import json
import random
import shutil
import subprocess
import sys
import tempfile
import time
import tracemalloc
from pathlib import Path

from tools.evidence_volumes import pack
from verification.evidence_volumes import reconstruct
from tools.host_lease import HostLease


def sha(path):
    result = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(65536), b""):
            result.update(block)
    return result.hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    results = []
    with tempfile.TemporaryDirectory(prefix="caissa-volume-controls-") as temporary:
        temporary = Path(temporary)
        original = temporary / "opaque-original.bin"
        generator = random.Random(32452843)
        with original.open("xb") as stream:
            for _ in range(545):
                stream.write(generator.randbytes(65536))
        size, expected = original.stat().st_size, sha(original)
        deadline = time.monotonic() + 300

        def tick():
            if time.monotonic() >= deadline:
                raise TimeoutError("original volume controls deadline exhausted")

        archive = temporary / "archive"
        tracemalloc.start()
        encoded = pack(original, archive, expected, size, tick)
        encode_peak = tracemalloc.get_traced_memory()[1]
        tracemalloc.stop()
        assert encoded["volumes"] == 3 and encode_peak < 8 * 1024**2
        tracemalloc.start()
        observed = reconstruct(
            archive / "VOLUMES.json",
            encoded["index_sha256"],
            expected,
            size,
            temporary / "restored.bin",
            maximum_seconds=60,
            tick=tick,
        )
        decode_peak = tracemalloc.get_traced_memory()[1]
        tracemalloc.stop()
        assert (
            sha(temporary / "restored.bin") == expected
            and observed["semantic_verification_required"] is True
            and observed["full_acceptance"] is False
            and decode_peak < 8 * 1024**2
        )
        results.append(
            {
                "case": "three-real-volumes",
                "raw_bytes": size,
                "volumes": 3,
                "encode_peak_python_bytes": encode_peak,
                "decode_peak_python_bytes": decode_peak,
                "observed": observed,
            }
        )
        # A real original chess journal is also treated as opaque bytes. The
        # codec never edits results or claims that this replaces chess replay.
        journal = Path(
            "results/full-model-planning-2026-10-23/fixed-prefix-owner-integration/corpus/000000/000000000.json"
        )
        journal_sha, journal_size = sha(journal), journal.stat().st_size
        packed = pack(
            journal, temporary / "original-journal", journal_sha, journal_size, tick
        )
        observed = reconstruct(
            temporary / "original-journal/VOLUMES.json",
            packed["index_sha256"],
            journal_sha,
            journal_size,
            temporary / "original-journal-restored.json",
            maximum_seconds=30,
            tick=tick,
        )
        assert sha(temporary / "original-journal-restored.json") == journal_sha
        results.append(
            {"case": "original-game-journal-byte-parity", "observed": observed}
        )
        cases = [
            "wrong-external-sha",
            "wrong-external-size",
            "unknown-schema",
            "promoted-semantic-pass",
            "boolean-byte-count",
            "traversal-member",
            "reordered-members",
            "missing-member",
            "extra-member",
            "linked-member",
            "wrong-compressed-sha",
            "wrong-decoded-sha",
            "truncated-gzip",
            "wrong-gzip-crc",
            "decompression-overflow",
            "existing-destination",
            "zero-deadline",
        ]
        for label in cases:
            tick()
            folder = temporary / label
            shutil.copytree(archive, folder)
            index = json.loads((folder / "VOLUMES.json").read_bytes())
            first = folder / "volumes/000000.gz"
            output = temporary / (label + ".raw")
            external_sha, external_size, seconds = expected, size, 60
            if label == "wrong-external-sha":
                external_sha = "0" * 64
            elif label == "wrong-external-size":
                external_size -= 1
            elif label == "unknown-schema":
                index["schema"] = "unsupported-volume-encoding"
            elif label == "promoted-semantic-pass":
                index["semantic_verification_required"] = False
            elif label == "boolean-byte-count":
                index["volumes"][0]["raw_bytes"] = True
            elif label == "traversal-member":
                index["volumes"][0]["path"] = "../escape.gz"
            elif label == "reordered-members":
                index["volumes"][0], index["volumes"][1] = (
                    index["volumes"][1],
                    index["volumes"][0],
                )
            elif label == "missing-member":
                first.unlink()
            elif label == "extra-member":
                (folder / "volumes/extra.gz").write_bytes(b"extra")
            elif label == "linked-member":
                first.unlink()
                first.symlink_to((archive / "volumes/000000.gz").resolve())
            elif label == "wrong-compressed-sha":
                index["volumes"][0]["gzip_sha256"] = "0" * 64
            elif label == "wrong-decoded-sha":
                index["volumes"][0]["raw_sha256"] = "0" * 64
            elif label in {
                "truncated-gzip",
                "wrong-gzip-crc",
                "decompression-overflow",
            }:
                if label == "decompression-overflow":
                    with original.open("rb") as stream:
                        body = stream.read(16777216) + b"x"
                    first.write_bytes(gzip.compress(body, mtime=0))
                else:
                    body = bytearray(first.read_bytes())
                    if label == "truncated-gzip":
                        body = body[:-4]
                    else:
                        body[-8] ^= 1
                    first.write_bytes(body)
                index["volumes"][0]["gzip_bytes"] = first.stat().st_size
                index["volumes"][0]["gzip_sha256"] = sha(first)
            elif label == "existing-destination":
                output.write_bytes(b"preserve existing bytes")
            elif label == "zero-deadline":
                seconds = 0
            (folder / "VOLUMES.json").write_text(json.dumps(index) + "\n")
            result = subprocess.run(
                [
                    sys.executable,
                    "-B",
                    "-m",
                    "verification.evidence_volumes",
                    str(folder / "VOLUMES.json"),
                    "--expected-index-sha256",
                    sha(folder / "VOLUMES.json"),
                    "--expected-original-sha256",
                    external_sha,
                    "--expected-original-bytes",
                    str(external_size),
                    "--output",
                    str(output),
                    "--maximum-seconds",
                    str(seconds),
                ],
                capture_output=True,
                text=True,
                timeout=65,
            )
            (args.output / (label + ".log")).write_text(result.stdout + result.stderr)
            value = json.loads(result.stdout)
            assert (
                result.returncode == 1
                and value["status"] == "rejected"
                and value["full_acceptance"] is False
            ), (label, value)
            if label == "existing-destination":
                assert output.read_bytes() == b"preserve existing bytes"
            else:
                assert not output.exists(), label
            results.append(
                {"case": label, "actual_exit": result.returncode, "observed": value}
            )
            shutil.rmtree(folder)
        bad = temporary / "wrong-source-pin"
        try:
            pack(original, bad, "0" * 64, size, tick)
        except ValueError as error:
            assert (
                "original input SHA" in str(error)
                and not (bad / "VOLUMES.json").exists()
            )
            results.append({"case": "encoder-wrong-original-pin", "reason": str(error)})
        else:
            raise AssertionError("encoder accepted a different original")
        assert sha(original) == expected
        try:
            pack(original, archive, expected, size, tick)
        except FileExistsError:
            results.append({"case": "encoder-refuses-existing-output"})
        else:
            raise AssertionError("encoder replaced existing evidence")
        changing = temporary / "changing-original.bin"
        shutil.copyfile(original, changing)
        calls = 0

        def change_input():
            nonlocal calls
            tick()
            calls += 1
            if calls == 3:
                with changing.open("ab") as stream:
                    stream.write(b"changed")

        failed = temporary / "changed-during-encoding"
        try:
            pack(changing, failed, expected, size, change_input)
        except ValueError as error:
            assert (
                "input changed" in str(error) and not (failed / "VOLUMES.json").exists()
            )
            results.append(
                {"case": "encoder-detects-input-mutation", "reason": str(error)}
            )
        else:
            raise AssertionError("encoder accepted a changing original")
        # Exercise the real owner entry point. This must refuse the competing
        # lease before creating a large-file scope or invoking compression.
        commit = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], text=True, timeout=5
        ).strip()
        owned = Path("runs/portable-evidence-v1") / journal_sha
        assert not owned.exists()
        lease = HostLease(Path("runs"))
        try:
            refusal = subprocess.run(
                [
                    sys.executable,
                    "-B",
                    "-m",
                    "tools.portable_evidence",
                    "--input",
                    str(journal),
                    "--input-sha256",
                    journal_sha,
                    "--input-bytes",
                    str(journal_size),
                    "--expected-commit",
                    commit,
                ],
                capture_output=True,
                text=True,
                timeout=30,
            )
        finally:
            lease.close()
        assert (
            refusal.returncode != 0
            and "already owns the host" in refusal.stderr
            and not owned.exists()
        ), (refusal.stdout + refusal.stderr)
        (args.output / "competing-owner.log").write_text(
            refusal.stdout + refusal.stderr
        )
        results.append(
            {
                "case": "actual-owner-refuses-inherited-host-contention",
                "actual_exit": refusal.returncode,
            }
        )
    record = {
        "status": "passed",
        "controls": results,
        "full_acceptance": False,
        "large_original_archive_executed": False,
    }
    (args.output / "VERIFICATION.json").write_text(json.dumps(record, indent=2) + "\n")
    print(
        json.dumps(
            {
                "status": "passed",
                "controls": len(results),
                "encode_peak_python_bytes": encode_peak,
                "decode_peak_python_bytes": decode_peak,
                "full_acceptance": False,
            }
        )
    )


if __name__ == "__main__":
    main()
