"""Full-CLI G13 forgeries and real native group-ownership probes.

The fixture has no performance sample. Metadata admission is never a gate pass.
"""

import argparse
import copy
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from tests.full_bundle import fixture, reference, seal, write
from tests.source_binding import repository
from tools.performance import options as producer_options
from verification.bundle import Bundle
from verification.native_session import NativeSession
from verification.performance import options as reader_options
from verification.performance_bundle import FILES, admit


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--engine", type=Path, required=True)
    ap.add_argument("--output", type=Path, required=True)
    args = ap.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    project = Path(__file__).resolve().parents[1]
    records = []
    with tempfile.TemporaryDirectory(prefix="caissa-performance-adapter-") as temporary:
        temporary = Path(temporary)
        source = temporary / "source"
        commit = repository(source)
        original = temporary / "original"
        inputs = fixture(original, project, source, commit)
        raw = original / "performance"
        raw.mkdir()
        profile = json.loads((project / "config/performance.json").read_text())
        write(raw / "PROFILE.json", profile)
        for key, name in FILES.items():
            if key not in {"config", "summary", "profile"}:
                (raw / name).write_text("{}\n" if name.endswith("jsonl") else "[]\n")
        config = {
            "schema": "caissa-performance-run-v2",
            "profile": "full-performance-unverified",
            "engine_sha256": inputs["engine"]["sha256"],
            "network_sha256": inputs["network"]["artifact"]["sha256"],
            "config_sha256": reference(original, "performance/PROFILE.json")["sha256"],
            "config": profile,
            "cpu_count": 8,
            "exact_optimizations": True,
            "lazy_neural": True,
            "started_unix": 100,
            "maximum_seconds": 600,
            "deadline_unix": 700,
        }
        summary = {
            "schema": "caissa-performance-summary-v2",
            "status": "passed",
            "files": {
                name: reference(original, "performance/" + name)["sha256"]
                for key, name in FILES.items()
                if key not in {"config", "summary", "profile"}
            },
        }
        write(raw / "CONFIG.json", config)
        write(raw / "SUMMARY.json", summary)

        def bind(root, value):
            domain = value["domains"]["G13"]
            domain["driver"] = "performance-observations-v2"
            domain["performance"] = {
                key: reference(root, "performance/" + name)
                for key, name in FILES.items()
            }
            domain["artifacts"] = list(domain["performance"].values())
            return seal(root, value)

        bind(original, inputs)
        with Bundle(original, 30) as bundle:
            bundle.verify_manifest()
            admit(bundle, inputs)
        reasons = {
            "diagnostic": "cannot promote",
            "no-lazy": "different deployment runtime",
            "program": "program/network differs",
            "model": "program/network differs",
            "cpu": "supported host sample",
            "boolean-cpu": "supported host sample",
            "threads": "thread/workload",
            "latency": "thread/workload",
            "hash": "thread/workload",
            "deadline": "cumulative deadline",
            "raw-hash": "observation digest",
            "alias": "distinct and declared",
            "undeclared": "distinct and declared",
            "false-pass-without-sample": "independent performance replay failed",
        }
        for case, reason in reasons.items():
            root = temporary / case
            shutil.copytree(original, root)
            value = copy.deepcopy(inputs)
            changed, workload, saved = (
                copy.deepcopy(config),
                copy.deepcopy(profile),
                copy.deepcopy(summary),
            )
            if case == "diagnostic":
                changed["profile"] = "diagnostic"
            elif case == "no-lazy":
                changed["lazy_neural"] = False
            elif case == "program":
                changed["engine_sha256"] = "0" * 64
            elif case == "model":
                changed["network_sha256"] = "0" * 64
            elif case == "cpu":
                changed["cpu_count"] = 4
            elif case == "boolean-cpu":
                changed["cpu_count"] = True
            elif case == "threads":
                workload["threads"] = [1, 2, 4]
            elif case == "latency":
                workload["latency_samples"] = 999
            elif case == "hash":
                workload["hash_mib"] = 8
            elif case == "deadline":
                changed["deadline_unix"] += 1
            elif case == "raw-hash":
                saved["files"]["measurements.jsonl"] = "0" * 64
            write(root / "performance/PROFILE.json", workload)
            changed["config"] = workload
            changed["config_sha256"] = reference(root, "performance/PROFILE.json")[
                "sha256"
            ]
            write(root / "performance/CONFIG.json", changed)
            write(root / "performance/SUMMARY.json", saved)
            pin = bind(root, value)
            domain = value["domains"]["G13"]
            if case == "alias":
                domain["performance"]["summary"] = domain["performance"]["config"]
                pin = seal(root, value)
            elif case == "undeclared":
                domain["artifacts"] = domain["artifacts"][:-1]
                pin = seal(root, value)
            command = [
                sys.executable,
                "-m",
                "verification.verify",
                str(root),
                "--checkout",
                str(source),
                "--expected-commit",
                commit,
                "--expected-inputs-sha256",
                pin,
                "--profile",
                "full",
                "--maximum-seconds",
                "30",
                "--replay-output",
                str(temporary / (case + "-replay")),
            ]
            result = subprocess.run(command, capture_output=True, text=True, timeout=35)
            (args.output / (case + ".log")).write_text(result.stdout + result.stderr)
            observed = json.loads(result.stdout)
            assert result.returncode == 1 and reason in observed.get("reason", ""), (
                case,
                observed,
                result.stderr,
            )
            records.append(
                {"case": case, "actual_exit": result.returncode, "observed": observed}
            )

    for evaluation in ["classical", "neural-native", "neural-scalar", "neural-blend"]:
        for lazy in [False, True]:
            actual = producer_options(
                profile, "/pinned-network", evaluation, 4, True, lazy
            )
            expected = reader_options(
                evaluation, 4, profile, "/pinned-network", True, lazy
            )
            assert actual == expected
            assert (
                actual.get("Lazy Neural") is True
                if lazy
                else "Lazy Neural" not in actual
            )
            assert actual["Threads"] == 4 and actual["Hash"] == 16
            if evaluation != "classical":
                assert actual["Neural Weight"] == (
                    10 if evaluation == "neural-blend" else 100
                )
                assert actual["Scalar Neural"] is (evaluation == "neural-scalar")
    probes = []
    for separate in [False, True]:
        with NativeSession(
            args.engine,
            {"Use Neural": False, "Lazy Neural": True},
            time.time() + 10,
            new_session=separate,
        ) as session:
            assert (os.getpgid(session.process.pid) != os.getpgrp()) is separate
            lines = session.search(
                "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1", 200
            )
            assert any(line.startswith("bestmove ") for line in lines)
        assert session.process.poll() is not None
        probes.append(
            {
                "separate_group": separate,
                "actual_exit": session.process.returncode,
                "uci": lines,
            }
        )
    write(args.output / "NATIVE_OWNERSHIP.json", probes)
    write(
        args.output / "CONTROLS.json",
        {
            "metadata_admissions": 1,
            "cases": records,
            "option_contracts": 8,
            "native_probes": 2,
            "full_sample_certified": False,
        },
    )
    print(
        json.dumps(
            {
                "status": "passed",
                "metadata_admissions": 1,
                "full_cli_rejections": 14,
                "option_contracts": 8,
                "actual_native_ownership_probes": 2,
                "full_G13_certified": False,
                "full_acceptance": False,
            }
        )
    )


if __name__ == "__main__":
    main()
