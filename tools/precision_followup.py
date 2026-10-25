"""Validation and instrumented-native checks within the original precision scope."""

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

from tools.campaign_process import Campaign, StageFailure
from tools.heuristic_study import avoid_decisive_matches

NATIVE_CASES = {
    "version",
    "core",
    "position",
    "rules",
    "evaluation",
    "table",
    "search",
    "notation",
    "uci",
    "position_line",
    "kernels",
    "dense_kernels",
    "neural_bounds",
    "evaluation_cache",
    "tactical_generation",
    "search_context",
    "lmr_window",
    "network_precision",
}


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def execute(args):
    avoid_decisive_matches()
    root = Path.cwd()
    if sha(args.protocol) != args.expected_protocol_sha256:
        raise ValueError(
            "precision follow-up differs from its external frozen identity"
        )
    rule = json.loads(args.protocol.read_text())
    original = json.loads(Path("config/precision-v4.json").read_text())
    if (
        sha(Path("config/precision-v4.json")) != rule["original_profile_sha256"]
        or rule["original_origin_unix"] != original["resources"]["origin_unix"]
        or rule["original_deadline_unix"] != original["resources"]["deadline_unix"]
        or rule["sanitizers"]
        != {
            "address": True,
            "undefined_behavior": True,
            "thread": True,
            "required_native_cases": 18,
            "selected_model_transitions": 1000000,
        }
    ):
        raise ValueError(
            "precision follow-up changed original budgets or required cases"
        )
    if os.environ.get("GITHUB_ACTIONS") == "true":
        if (
            not 2 <= int(os.environ["GITHUB_RUN_NUMBER"]) <= 3
            or int(os.environ["GITHUB_RUN_ATTEMPT"]) != 1
        ):
            raise ValueError("precision follow-up hosted attempt ceiling exhausted")
    commit = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], text=True, timeout=5
    ).strip()
    if commit != args.expected_commit or subprocess.check_output(
        ["git", "status", "--porcelain"], text=True, timeout=5
    ):
        raise ValueError("precision follow-up must use its trusted clean checkout")
    remaining = min(1800, rule["original_deadline_unix"] - time.time())
    if remaining <= 0:
        raise TimeoutError("original precision profile wall budget exhausted")
    network = Path("results/precision-v4-2026-10-25/selected-v4.cai").resolve()
    if sha(network) != rule["validation"]["network_sha256"]:
        raise ValueError("precision follow-up changed the experimental network")
    campaign = Campaign(
        args.output,
        {
            "source_commit": commit,
            "protocol_sha256": sha(args.protocol),
            "original_origin_unix": rule["original_origin_unix"],
            "original_deadline_unix": rule["original_deadline_unix"],
            "network_sha256": sha(network),
            "full_acceptance": False,
        },
        remaining,
        absolute_deadline=rule["original_deadline_unix"],
    )
    failed, reports = [], {}
    py = sys.executable
    try:
        # The new checks do not alter any original native implementation.
        campaign.run(
            "unchanged-native-source",
            [
                "git",
                "diff",
                "--exit-code",
                "d386b8df2e2c1a9ab2cf67660595fcad90ba8eb4",
                "--",
                "CMakeLists.txt",
                "src",
                "include",
                "apps",
            ],
            15,
        )
        for mode, flags, marker in [
            ("release", ["-DCMAKE_BUILD_TYPE=Release"], None),
            (
                "asan",
                ["-DCMAKE_BUILD_TYPE=RelWithDebInfo", "-DCAISSA_SANITIZE=ON"],
                "-fsanitize=address,undefined",
            ),
            (
                "tsan",
                ["-DCMAKE_BUILD_TYPE=RelWithDebInfo", "-DCAISSA_TSAN=ON"],
                "-fsanitize=thread",
            ),
        ]:
            build = root / ("build-precision-followup-" + mode)
            try:
                campaign.run(
                    "configure-" + mode,
                    [
                        "cmake",
                        "-S",
                        ".",
                        "-B",
                        str(build),
                        "-DCMAKE_EXPORT_COMPILE_COMMANDS=ON",
                        *flags,
                    ],
                    60,
                )
                campaign.run(
                    "build-" + mode, ["cmake", "--build", str(build), "-j", "2"], 240
                )
                cases = json.loads(
                    subprocess.check_output(
                        ["ctest", "--test-dir", str(build), "--show-only=json-v1"],
                        text=True,
                        timeout=10,
                    )
                )
                if {row["name"] for row in cases["tests"]} != NATIVE_CASES or len(
                    cases["tests"]
                ) != 18:
                    raise ValueError("instrumented precision case inventory differs")
                if marker:
                    commands = json.loads((build / "compile_commands.json").read_text())
                    if not commands or any(
                        marker not in row["command"] for row in commands
                    ):
                        raise ValueError(
                            "requested sanitizer was not compiled into every native target"
                        )
                campaign.run(
                    "native-" + mode,
                    ["ctest", "--test-dir", str(build), "--output-on-failure"],
                    600,
                )
                campaign.run(
                    "restoration-" + mode,
                    [str(build / "network_test"), str(network), "1000000"],
                    600,
                )
                reports[mode] = {
                    "status": "passed",
                    "native_cases": 18,
                    "transitions": 1000000,
                    "engine_sha256": sha(build / "caissa"),
                    "instrumentation": marker,
                }
                (args.output / ("cases-" + mode + ".json")).write_text(
                    json.dumps(cases, indent=2) + "\n"
                )
                (args.output / ("compile-" + mode + ".json")).write_bytes(
                    (build / "compile_commands.json").read_bytes()
                )
                if mode == "release":
                    campaign.run(
                        "deployed-validation",
                        [
                            py,
                            "-m",
                            "verification.deployment_loss",
                            "--engine",
                            str(build / "caissa"),
                            "--network",
                            str(network),
                            "--slice",
                            "results/precision-v4-inputs/validation",
                            "--protocol",
                            str(args.protocol.resolve()),
                            "--expected-protocol-sha256",
                            args.expected_protocol_sha256,
                            "--deadline-unix",
                            str(rule["original_deadline_unix"]),
                            "--output",
                            str((args.output / "validation").resolve()),
                        ],
                        125,
                    )
            except StageFailure as error:
                failed.append(
                    {
                        "mode": mode,
                        "stage": error.record["stage"],
                        "exit": error.record["exit"],
                        "reason": error.record["reason"],
                    }
                )
                reports[mode] = {"status": "failed", "actual_failure": failed[-1]}
        result = {
            "status": "passed" if not failed else "completed with failed gates",
            "reports": reports,
            "failed_domains": failed,
            "original_origin_unix": rule["original_origin_unix"],
            "original_deadline_unix": rule["original_deadline_unix"],
            "source_commit": commit,
            "network_sha256": sha(network),
            "protocol_sha256": sha(args.protocol),
            "model_selection_changed": False,
            "test_arrays_opened": False,
            "full_acceptance": False,
            "playing_strength_measured": False,
        }
        (args.output / "FOLLOWUP.json").write_text(json.dumps(result, indent=2) + "\n")
        campaign.close(result["status"], result)
        print(json.dumps(result))
        return 2 if failed else 0
    except BaseException as error:
        campaign.close("failed", {"error": repr(error), "full_acceptance": False})
        raise


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--protocol", type=Path, required=True)
    parser.add_argument("--expected-protocol-sha256", required=True)
    parser.add_argument("--expected-commit", required=True)
    parser.add_argument("--output", type=Path, required=True)
    return execute(parser.parse_args())


if __name__ == "__main__":
    raise SystemExit(main())
