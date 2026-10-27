"""Two new clean builds with actual compiler/link receipts, not saved-image attribution."""

import argparse
import contextlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from tools.campaign_process import Campaign, atomic
from tools.compiler_capture import retain, sha
from tools.host_lease import HostLease
from tools.recovery_scope import tree_bytes
from verification.source import NATIVE, PRODUCT, require, snapshot


def execute(checkout, commit, profile_sha, output):
    checkout, output = checkout.resolve(), output.resolve()
    profile_path = checkout / "config/build-attribution-v1.json"
    require(sha(profile_path) == profile_sha, "external build profile differs")
    rule = json.loads(profile_path.read_text())
    limits = json.loads(
        (checkout / "config/build-attribution-amendment-v1.json").read_text()
    )
    require(
        subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=checkout, text=True
        ).strip()
        == commit,
        "external build source differs",
    )
    source = snapshot(checkout, commit, PRODUCT)
    require(
        all(sha(checkout / name) == value for name, value in source.items()),
        "build checkout source changed",
    )
    native = snapshot(checkout, commit, NATIVE)
    require(
        native == snapshot(checkout, rule["compiled_original_source"], NATIVE),
        "native bytes differ from original saved source",
    )
    compiler = shutil.which("clang++")
    require(compiler is not None, "Clang compiler unavailable")
    # Preserve the clang++ driver name, which selects C++ runtime linkage.
    compiler = str(Path(compiler).absolute())
    environment = {
        k: os.environ[k]
        for k in ["PATH", "HOME", "TMPDIR", "SYSTEMROOT"]
        if k in os.environ
    }
    environment.update(
        ZERO_AR_DATE="1",
        SOURCE_DATE_EPOCH=subprocess.check_output(
            ["git", "show", "-s", "--format=%ct", commit], cwd=checkout, text=True
        ).strip(),
    )
    with contextlib.closing(HostLease(checkout / "runs")) as lease:

        def guard():
            lease.check()
            require(
                shutil.disk_usage(output).free >= limits["minimum_free_bytes"],
                "build free-space reserve exhausted",
            )
            require(
                tree_bytes(output) <= limits["maximum_output_bytes_per_platform"],
                "build output byte ceiling exhausted",
            )

        campaign = Campaign(
            output,
            {
                "source_commit": commit,
                "profile_sha256": profile_sha,
                "environment": environment,
            },
            rule["maximum_seconds"],
            absolute_deadline=limits["deadline_unix"],
            resource_guard=guard,
        )
        try:
            atomic(
                output / "SOURCE_INPUTS.json",
                {"commit": commit, "files": source, "native": native},
            )
            shutil.copyfile(profile_path, output / "PROFILE.json")
            toolchain = output / "toolchain"
            toolchain.mkdir()
            atomic(
                toolchain / "COMPILER.json", retain(compiler, toolchain, 512 * 1024**2)
            )
            builds = []
            for number in range(1, 3):
                folder = output / ("build-" + str(number))
                folder.mkdir()
                tree, build, trace = (
                    folder / "checkout",
                    folder / "work",
                    folder / "trace",
                )

                def run(stage, command, seconds=120):
                    return campaign.run(
                        f"build-{number}-{stage}",
                        list(map(str, command)),
                        seconds,
                        cwd=checkout,
                        env=environment,
                    )

                run(
                    "clone",
                    [
                        "git",
                        "clone",
                        "--quiet",
                        "--no-hardlinks",
                        "--no-checkout",
                        checkout,
                        tree,
                    ],
                )
                run(
                    "checkout",
                    ["git", "-C", tree, "checkout", "--quiet", "--detach", commit],
                )
                launcher = [
                    sys.executable,
                    str(tree / "tools/compiler_capture.py"),
                    "--source",
                    str(tree),
                    "--output",
                    str(trace),
                ]
                prefix = " ".join(
                    [
                        "-ffile-prefix-map=" + str(tree) + "=/caissa/source",
                        "-ffile-prefix-map=" + str(build) + "=/caissa/build",
                        "-fdebug-compilation-dir=/caissa/build",
                    ]
                )
                run(
                    "configure",
                    [
                        "cmake",
                        "-S",
                        tree,
                        "-B",
                        build,
                        "-G",
                        "Ninja",
                        "-DCMAKE_BUILD_TYPE=Release",
                        "-DCAISSA_NETWORK_WIDTH=64",
                        "-DCAISSA_SANITIZE=OFF",
                        "-DCAISSA_TSAN=OFF",
                        "-DCMAKE_EXPORT_COMPILE_COMMANDS=ON",
                        "-DCMAKE_CXX_COMPILER=" + compiler,
                        "-DCMAKE_CXX_COMPILER_LAUNCHER="
                        + ";".join(launcher + ["--mode", "compile", "--"]),
                        "-DCMAKE_CXX_LINKER_LAUNCHER="
                        + ";".join(launcher + ["--mode", "link", "--"]),
                        "-DCMAKE_CXX_FLAGS=" + prefix,
                    ],
                )
                for name, command in {
                    "compiler": [compiler, "--version"],
                    "cmake": ["cmake", "--version"],
                    "ninja": ["ninja", "--version"],
                }.items():
                    run(name + "-version", command, 10)
                run(
                    "compile",
                    [
                        "cmake",
                        "--build",
                        build,
                        "--target",
                        "caissa",
                        "--parallel",
                        "2",
                        "--verbose",
                    ],
                    600,
                )
                run("graph", ["ninja", "-C", build, "-t", "commands", "caissa"], 10)
                shutil.copyfile(
                    build / "compile_commands.json", folder / "compile_commands.json"
                )
                shutil.copyfile(build / "CMakeCache.txt", folder / "CMakeCache.txt")
                shutil.copyfile(build / "caissa", folder / "caissa")
                units = [
                    json.loads(p.read_text())
                    for p in trace.glob("*.json")
                    if p.name != "link.json"
                ]
                builds.append(
                    {
                        "directory": folder.name,
                        "binary_sha256": sha(folder / "caissa"),
                        "unit_outputs": {
                            r["source"]: r["output"]["sha256"] for r in units
                        },
                    }
                )
                atomic(
                    output / "BUILD_PROGRESS.json",
                    {"builds": builds, "full_G15_certified": False},
                )
            if builds[0]["binary_sha256"] != builds[1]["binary_sha256"]:
                left = (output / "build-1/caissa").read_bytes()
                right = (output / "build-2/caissa").read_bytes()
                difference = {
                    "builds": builds,
                    "lengths": [len(left), len(right)],
                    "first_differing_bytes": [
                        [index, a, b]
                        for index, (a, b) in enumerate(zip(left, right))
                        if a != b
                    ][:32],
                    "different_objects": [
                        name
                        for name, digest in builds[0]["unit_outputs"].items()
                        if builds[1]["unit_outputs"].get(name) != digest
                    ],
                }
                atomic(output / "BINARY_DIFFERENCE.json", difference)
                print(json.dumps(difference), flush=True)
                raise ValueError("two clean builds produced different executable bytes")
            result = {
                "status": "recorded",
                "source_commit": commit,
                "profile_sha256": profile_sha,
                "builds": builds,
                "compiler_attribution_applies_to_new_builds_only": True,
                "saved_original_compiler_invocation_proven": False,
                "full_G15_certified": False,
                "full_acceptance": False,
            }
            atomic(output / "BUILD_REPRODUCTION.json", result)
            campaign.close("recorded two new builds", result)
            return result
        except BaseException as error:
            campaign.close("failed", {"reason": str(error)})
            raise


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--checkout", type=Path, required=True)
    parser.add_argument("--expected-commit", required=True)
    parser.add_argument("--profile-sha256", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(
        json.dumps(
            execute(
                args.checkout, args.expected_commit, args.profile_sha256, args.output
            )
        )
    )


if __name__ == "__main__":
    main()
