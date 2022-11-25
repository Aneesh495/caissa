"""Bind instrumented native tests to trusted Git bytes and rerun each binary.

Reads the original build and logs without changing CTest's retained records.
The independent replay writes only to a separate caller-selected directory.
"""

import argparse
import hashlib
import json
import re
import subprocess
import time
from pathlib import Path

from verification.acquisition import sha
from verification.protocol import read_json

TESTS = {
    "version": "caissa",
    "core": "core_test",
    "position": "position_test",
    "rules": "rules_test",
    "evaluation": "evaluation_test",
    "table": "table_test",
    "search": "search_test",
    "notation": "notation_test",
    "uci": "uci_test",
    "position_line": "position_line_test",
    "kernels": "kernel_test",
    "dense_kernels": "dense_kernel_test",
    "neural_bounds": "neural_bounds_test",
    "evaluation_cache": "evaluation_cache_test",
    "tactical_generation": "tactical_generation_test",
}


def require(value, reason):
    if not value:
        raise ValueError(reason)


def load(path, ceiling=4 * 1024 * 1024):
    require(
        not path.is_symlink() and 0 < path.stat().st_size <= ceiling,
        "native build metadata size or link contract differs",
    )
    return read_json(path.read_text())


def trusted_sources(checkout, commit):
    # Existing native campaigns retain their original source-selection policy.
    from verification.source import LEGACY, snapshot

    return snapshot(checkout, commit, LEGACY)


def verify(root, checkout, commit, replay_output, maximum_seconds=600):
    require(
        1 <= maximum_seconds <= 1800, "finite instrumented replay deadline required"
    )
    started = time.time()
    deadline = started + maximum_seconds

    def remaining(cap):
        value = min(cap, deadline - time.time())
        require(value > 0, "instrumented native replay deadline exhausted")
        return value

    config = load(root / "CONFIG.json")
    finished = load(root / "CAMPAIGN.json")
    identity = load(root / "IDENTITY.json")
    require(
        config["source_commit"] == identity["source_commit"] == commit,
        "native campaign source differs from trusted identity",
    )
    require(
        config["maximum_seconds"] == 1200
        and config["build_type"] == "RelWithDebInfo"
        and config["network_width"] == 64,
        "native race build resource or architecture differs",
    )
    expected = trusted_sources(checkout, commit)
    require(
        config["source_files"] == expected,
        "native campaign source inventory differs from trusted Git blobs",
    )
    source = root / "source"
    build = root / "build"
    for name, digest in expected.items():
        remaining(1)
        require(
            not (source / name).is_symlink() and sha(source / name) == digest,
            "archived native source changed: " + name,
        )
    require(
        finished["status"]
        == "passed all15 ThreadSanitizer native cases and20000 incremental network transitions; current-core diagnostic only"
        and 0 <= finished["seconds_this_campaign"] <= 1200,
        "original native race campaign did not complete inside its ceiling",
    )
    cache = (build / "CMakeCache.txt").read_text()
    require(len(cache) <= 1024 * 1024, "native build cache byte ceiling")
    settings = {
        line.split(":", 1)[0]: line.split("=", 1)[1]
        for line in cache.splitlines()
        if not line.startswith(("//", "#")) and ":" in line and "=" in line
    }
    require(
        settings.get("CAISSA_TSAN") == "ON"
        and settings.get("CAISSA_SANITIZE") == "OFF"
        and settings.get("CAISSA_NETWORK_WIDTH") == "64"
        and settings.get("CMAKE_BUILD_TYPE") == "RelWithDebInfo"
        and Path(settings["CMAKE_HOME_DIRECTORY"]).resolve() == source.resolve(),
        "native build is not the frozen separate ThreadSanitizer source",
    )
    flags = (build / "CMakeFiles/caissa_core.dir/flags.make").read_text()
    require(
        len(flags) <= 65536
        and "-fsanitize=thread" in flags
        and "-fsanitize=address" not in flags,
        "native core compile flags lack separate thread instrumentation",
    )
    binaries = {name: build / executable for name, executable in TESTS.items()}
    binaries["network_transitions"] = build / "network_test"
    hashes = {name: sha(path) for name, path in binaries.items()}
    require(
        hashes["version"] == identity["binary_sha256"],
        "instrumented native executable changed",
    )
    for name, path in binaries.items():
        symbols = subprocess.run(
            ["nm", "-u", str(path)],
            capture_output=True,
            text=True,
            timeout=remaining(10),
        )
        require(
            symbols.returncode == 0
            and len(symbols.stdout) <= 4 * 1024 * 1024
            and "__tsan_init" in symbols.stdout,
            "native test binary lacks linked ThreadSanitizer hooks: " + name,
        )
        if name == "version":
            require(
                "__tsan_read" in symbols.stdout and "__tsan_write" in symbols.stdout,
                "native runtime lacks instrumented memory accesses",
            )
    journal = []
    with (root / "COMMANDS.jsonl").open() as stream:
        for line in stream:
            require(
                len(line) <= 1024 * 1024 and len(journal) < 1000,
                "native command journal exceeds ceiling",
            )
            journal.append(read_json(line))
    records = {row["stage"]: row for row in journal if row["event"] == "stage-finished"}
    required = {
        "configure",
        "build",
        "native-races",
        "transitions-diagnostic-v2",
        "transitions-residual-prefix-diagnostic",
    }
    require(
        records.keys() == required,
        "native instrumented stage inventory is incomplete or duplicated",
    )
    require(
        len([row for row in journal if row["event"] == "stage-finished"])
        == len(required),
        "native instrumented journal duplicated a stage",
    )
    for name, row in records.items():
        require(
            row["exit"] == 0
            and row["reason"] == "completed"
            and row["wall_seconds"] >= 0
            and row["discarded_output_bytes"] == 0
            and row["log"] == name + ".log",
            "native instrumented stage failed or discarded evidence",
        )
        path = root / row["log"]
        require(
            0 < path.stat().st_size <= 32 * 1024 * 1024
            and sha(path) == row["log_sha256"],
            "native instrumented stage log changed",
        )
        require(
            "WARNING: ThreadSanitizer" not in path.read_text()
            and "SUMMARY: ThreadSanitizer" not in path.read_text(),
            "original native log contains a race report",
        )
    detail = (build / "Testing/Temporary/LastTest.log").read_text()
    require(len(detail) <= 4 * 1024 * 1024, "native original test detail byte ceiling")
    names = re.findall(r"^\d+/15 Testing: ([a-z_]+)$", detail, re.M)
    require(
        names == list(TESTS)
        and detail.count("Test Passed.") == 15
        and "Test Failed." not in detail,
        "native original CTest sample differs or contains failures",
    )
    for name in ("diagnostic-v2", "residual-prefix-diagnostic"):
        row = read_json((root / ("transitions-" + name + ".log")).read_text())
        require(
            row["status"] == "passed" and row["transitions"] == 10000,
            "original instrumented model transition sample is incomplete",
        )
    require(
        not replay_output.resolve().is_relative_to(root.resolve()),
        "independent instrumented replay must preserve original evidence",
    )
    replay_output.mkdir(parents=True, exist_ok=False)
    observations = []
    for name, path in binaries.items():
        arguments = []
        if name == "version":
            arguments = ["--version"]
        elif name == "neural_bounds":
            arguments = [str(source / "models/residual-prefix-diagnostic.cai")]
        elif name in ("evaluation_cache", "tactical_generation"):
            arguments = [
                str(source / "models/residual-prefix-diagnostic.cai"),
                str(source / "models/diagnostic-v2.cai"),
            ]
        workloads = (
            [arguments]
            if name != "network_transitions"
            else [
                [str(source / "models" / (model + ".cai")), "10000"]
                for model in ("diagnostic-v2", "residual-prefix-diagnostic")
            ]
        )
        for index, args in enumerate(workloads):
            begin = time.time()
            result = subprocess.run(
                [str(path), *args], capture_output=True, timeout=remaining(180)
            )
            require(
                len(result.stdout) + len(result.stderr) <= 8 * 1024 * 1024,
                "independent native output exceeds byte ceiling",
            )
            prefix = name + "-" + str(index)
            (replay_output / (prefix + ".stdout")).write_bytes(result.stdout)
            (replay_output / (prefix + ".stderr")).write_bytes(result.stderr)
            row = {
                "test": name,
                "index": index,
                "argv": [str(path), *args],
                "exit": result.returncode,
                "wall_seconds": time.time() - begin,
                "stdout_sha256": hashlib.sha256(result.stdout).hexdigest(),
                "stderr_sha256": hashlib.sha256(result.stderr).hexdigest(),
            }
            observations.append(row)
            with (replay_output / "COMMANDS.jsonl").open("a") as log:
                log.write(json.dumps(row, separators=(",", ":")) + "\n")
            require(
                result.returncode == 0
                and b"WARNING: ThreadSanitizer" not in result.stderr
                and b"SUMMARY: ThreadSanitizer" not in result.stderr,
                "independent instrumented native test failed: " + name,
            )
    require(
        all(sha(binaries[name]) == digest for name, digest in hashes.items()),
        "instrumented native binary changed during replay",
    )
    require(
        all(sha(source / name) == digest for name, digest in expected.items()),
        "archived instrumented source changed during replay",
    )
    result = {
        "status": "passed",
        "scope": "trusted-source ThreadSanitizer native replay",
        "source_commit": commit,
        "binary_sha256": hashes["version"],
        "test_binary_sha256": hashes,
        "independently_executed_native_cases": 15,
        "independently_executed_model_transitions": 20000,
        "wall_seconds": time.time() - started,
        "full_acceptance": False,
        "limitations": "Observed executions contain no race reports. Final selected-model binding, controlled performance and parallel strength remain separate gates.",
    }
    (replay_output / "SUMMARY.json").write_text(json.dumps(result, indent=2) + "\n")
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("evidence", type=Path)
    parser.add_argument("--checkout", type=Path, required=True)
    parser.add_argument("--expected-commit", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--maximum-seconds", type=int, default=600)
    args = parser.parse_args()
    try:
        print(
            json.dumps(
                verify(
                    args.evidence,
                    args.checkout,
                    args.expected_commit,
                    args.output,
                    args.maximum_seconds,
                )
            )
        )
        return 0
    except (
        ValueError,
        KeyError,
        OSError,
        IndexError,
        subprocess.SubprocessError,
    ) as error:
        print(
            json.dumps(
                {"status": "rejected", "reason": str(error), "full_acceptance": False}
            )
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
