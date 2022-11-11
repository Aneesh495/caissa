"""Independently replay saved instrumented programs and verify native evidence.

No producer parser, test runner or aggregate is imported. The trusted checkout,
external saved-program identity and original profile deadline are mandatory.
"""

import argparse
import hashlib
import json
import math
import shutil
import subprocess
import time
from pathlib import Path

from tools.campaign_process import Campaign
from tools.heuristic_study import avoid_decisive_matches
from verification.protocol import read_json

EXPECTED = {
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


def require(value, reason):
    if not value:
        raise ValueError(reason)


def digest(path):
    require(
        path.is_file()
        and not path.is_symlink()
        and 0 < path.stat().st_size <= 32 * 1024 * 1024,
        "saved native input byte ceiling or unsafe file",
    )
    result = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1048576), b""):
            result.update(block)
    return result.hexdigest()


def verify(args):
    avoid_decisive_matches()
    source = args.checkout.resolve()
    evidence = args.evidence.resolve()
    require(
        not args.output.resolve().is_relative_to(evidence),
        "native replay must preserve original evidence",
    )
    require(
        subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=source, text=True, timeout=5
        ).strip()
        == args.expected_commit,
        "trusted native checkout differs from expected source",
    )
    require(
        not subprocess.check_output(
            ["git", "status", "--porcelain"], cwd=source, text=True, timeout=5
        ),
        "trusted native source is dirty",
    )
    require(
        math.isfinite(args.maximum_seconds) and 0 < args.maximum_seconds <= 600,
        "native replay original independent-time ceiling differs",
    )
    profile = read_json((source / "config/precision-v4-followup.json").read_text())
    require(
        args.deadline_unix == profile["original_deadline_unix"],
        "native replay original deadline differs",
    )
    require(
        digest(evidence / "PROGRAMS.json") == args.expected_programs_sha256,
        "saved native programs differ from the external frozen identity",
    )
    programs = read_json((evidence / "PROGRAMS.json").read_text())
    require(
        programs["source_commit"] == args.expected_commit
        and set(programs["modes"]) == {"release", "asan", "tsan"},
        "saved program source or mode inventory differs",
    )
    tracked = subprocess.check_output(
        ["git", "ls-files", "-z"], cwd=source, text=True, timeout=5
    ).split("\0")
    expected_inputs = {
        name
        for name in tracked
        if name == "CMakeLists.txt"
        or (
            name.startswith(("src/", "include/", "apps/", "tests/"))
            and name.endswith((".cpp", ".hpp"))
        )
        or (name.startswith("models/") and name.endswith(".cai"))
    }
    require(
        set(programs["source_files"]) == expected_inputs,
        "native compilation input inventory differs",
    )
    for name, expected in programs["source_files"].items():
        path = Path(name)
        require(
            not path.is_absolute() and ".." not in path.parts,
            "unsafe saved source path",
        )
        require(
            digest(source / path) == expected,
            "native source differs from saved compilation",
        )
        committed = subprocess.check_output(
            ["git", "show", args.expected_commit + ":" + name], cwd=source, timeout=5
        )
        require(
            hashlib.sha256(committed).hexdigest() == expected,
            "native source differs from trusted commit",
        )
    commands = [
        read_json(line)
        for line in (evidence / "COMMANDS.jsonl").read_text().splitlines()
    ]
    finished = {
        row["stage"]: row for row in commands if row.get("event") == "stage-finished"
    }
    identities = {}
    for mode, marker in [
        ("release", None),
        ("asan", "-fsanitize=address,undefined"),
        ("tsan", "-fsanitize=thread"),
    ]:
        saved = programs["modes"][mode]
        require(
            set(saved["cases"]) == EXPECTED and len(saved["binaries"]) == 19,
            "saved native case/program inventory is incomplete",
        )
        for relative, expected in saved["binaries"].items():
            path = Path(relative)
            require(
                path.parts[:2] == ("bin", mode)
                and len(path.parts) == 3
                and ".." not in path.parts,
                "unsafe saved executable path",
            )
            require(
                digest(evidence / path) == expected, "saved executable bytes changed"
            )
        compilation = read_json((evidence / f"compile-{mode}.json").read_text())
        require(
            bool(compilation)
            and (
                marker is None or all(marker in row["command"] for row in compilation)
            ),
            "native instrumentation is absent from compiled targets",
        )
        case_record = read_json((evidence / f"cases-{mode}.json").read_text())
        require(
            {row["name"] for row in case_record["tests"]} == EXPECTED
            and len(case_record["tests"]) == 18,
            "actual CTest inventory differs",
        )
        for name, command in saved["cases"].items():
            row = next(row for row in case_record["tests"] if row["name"] == name)
            require(
                command == row["command"], "saved native invocation differs from CTest"
            )
        for stage in ["build-" + mode, "native-" + mode, "restoration-" + mode]:
            observed = finished[stage]
            require(
                observed["exit"] == 0
                and observed["reason"] == "completed"
                and observed["discarded_output_bytes"] == 0
                and digest(evidence / observed["log"]) == observed["log_sha256"],
                "native stage failed, dropped output or changed its log",
            )
        restored = read_json((evidence / f"restoration-{mode}.log").read_text())
        require(
            restored["status"] == "passed" and restored["transitions"] == 1000000,
            "original selected-model restoration sample is incomplete",
        )
        detail = (evidence / f"native-detail-{mode}.log").read_text()
        require(
            detail.count("Test Passed.") == 18,
            "native detailed test execution is incomplete",
        )
        identities[mode] = saved
    network = source / "results/precision-v4-2026-10-25/selected-v4.cai"
    require(
        digest(network)
        == "52d0306143392ad683c3ebb09fe013f34e1f9e2bc44d3aa153b32314207374b7",
        "native replay selected network differs",
    )
    remaining = min(args.maximum_seconds, args.deadline_unix - time.time())
    require(remaining > 0, "original independent native replay budget exhausted")
    campaign = Campaign(
        args.output,
        {
            "source_commit": args.expected_commit,
            "programs_sha256": args.expected_programs_sha256,
            "network_sha256": digest(network),
            "original_deadline_unix": args.deadline_unix,
            "full_acceptance": False,
        },
        remaining,
        absolute_deadline=args.deadline_unix,
    )
    replayed = 0
    try:
        for mode, saved in identities.items():
            binaries = args.output / "bin" / mode
            binaries.mkdir(parents=True)
            for relative, expected in saved["binaries"].items():
                target = binaries / Path(relative).name
                shutil.copy2(evidence / relative, target)
                target.chmod(0o755)
                require(digest(target) == expected, "copied native replay bytes differ")
            for name in sorted(EXPECTED):
                command = saved["cases"][name]
                executable = Path(command[0]).name
                require(
                    executable in {Path(p).name for p in saved["binaries"]},
                    "CTest selected an undeclared program",
                )
                arguments = []
                for text in command[1:]:
                    if text.endswith(".cai"):
                        path = Path(text)
                        require(
                            path.resolve().is_relative_to(source / "models"),
                            "native test requested an undeclared model",
                        )
                        require(
                            str(path.relative_to(source)) in programs["source_files"],
                            "native model is absent from trusted inputs",
                        )
                    arguments.append(text)
                campaign.run(
                    mode + "-" + name,
                    [str((binaries / executable).resolve()), *arguments],
                    240,
                    cwd=source,
                )
                replayed += 1
            campaign.run(
                mode + "-selected-restoration",
                [str((binaries / "network_test").resolve()), str(network), "1000000"],
                600,
                cwd=source,
            )
            restored = read_json(
                (args.output / (mode + "-selected-restoration.log")).read_text()
            )
            require(
                restored["status"] == "passed" and restored["transitions"] == 1000000,
                "independent selected-model restoration did not complete",
            )
        require(replayed == 54, "independent native sample was incomplete")
        result = {
            "status": "passed",
            "independently_reexecuted_native_cases": replayed,
            "cases_per_mode": 18,
            "selected_model_transitions_per_mode": 1000000,
            "modes": ["release", "asan", "tsan"],
            "source_commit": args.expected_commit,
            "programs_sha256": args.expected_programs_sha256,
            "network_sha256": digest(network),
            "full_acceptance": False,
            "scope": "Exact saved-program replay and instrumentation/identity checks; full thread-strength and whole-project acceptance remain separate",
        }
        (args.output / "INDEPENDENT.json").write_text(
            json.dumps(result, indent=2) + "\n"
        )
        campaign.close("passed independent native replay", result)
        print(json.dumps(result))
    except BaseException as error:
        campaign.close("failed", {"error": repr(error), "full_acceptance": False})
        raise


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--checkout", type=Path, required=True)
    parser.add_argument("--expected-commit", required=True)
    parser.add_argument("--expected-programs-sha256", required=True)
    parser.add_argument("--maximum-seconds", type=float, default=600)
    parser.add_argument("--deadline-unix", type=float, required=True)
    parser.add_argument("--output", type=Path, required=True)
    verify(parser.parse_args())


if __name__ == "__main__":
    main()
