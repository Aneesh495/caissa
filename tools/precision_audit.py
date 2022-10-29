"""Bounded encoding experiment using an existing validation-selected checkpoint.

No training, seed selection, test-array access or match execution occurs here.
The old q1024 failure and active strength actors remain immutable.
"""

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path

from tools.campaign_process import Campaign, StageFailure
from tools.heuristic_study import avoid_decisive_matches


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--engine", type=Path, required=True)
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--protocol", type=Path, required=True)
    parser.add_argument("--expected-protocol-sha256", required=True)
    parser.add_argument("--expected-commit", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    avoid_decisive_matches()
    if sha(args.protocol) != args.expected_protocol_sha256:
        raise ValueError("precision profile differs from its external frozen identity")
    rule = json.loads(args.protocol.read_text())
    net, resource = rule["network"], rule["resources"]
    expected = {
        "format": 4,
        "training_format": 3,
        "width": 64,
        "scale": 4096,
        "clip": 8188,
        "classical_contract": 1,
        "neural_weight": 10,
        "probes": 100000,
        "probe_seed": 32452867,
        "maximum_float_error_cp": 32,
        "error_contract": "unclamped-quantization-and-clamped-inference",
        "export_contract": "v3-float-to-v4-q4096-same-activation-ceiling-v1",
    }
    if (
        net != expected
        or rule["schema"] != "caissa-precision-profile-v1"
        or rule["status"] != "frozen"
    ):
        raise ValueError("frozen precision contract or numerical endpoint changed")
    if sha(args.checkpoint) != rule["checkpoint_sha256"]:
        raise ValueError(
            "precision experiment changed the validation-selected checkpoint"
        )
    if (
        subprocess.check_output(
            ["git", "rev-parse", "HEAD"], text=True, timeout=5
        ).strip()
        != args.expected_commit
    ):
        raise ValueError("precision source differs from trusted checkout")
    if subprocess.check_output(["git", "status", "--porcelain"], text=True, timeout=5):
        raise ValueError("precision source must be committed")
    if os.environ.get("GITHUB_ACTIONS") == "true":
        if (
            int(os.environ["GITHUB_RUN_NUMBER"]) > 3
            or int(os.environ["GITHUB_RUN_ATTEMPT"]) != 1
        ):
            raise ValueError("frozen precision workflow attempt ceiling exhausted")
    remaining = min(1800, resource["deadline_unix"] - time.time())
    if remaining <= 0:
        raise TimeoutError("precision profile original wall deadline exhausted")
    engine = args.engine.resolve()
    checkpoint = args.checkpoint.resolve()
    output = args.output.resolve()
    bindings = {
        "protocol_sha256": args.expected_protocol_sha256,
        "source_commit": args.expected_commit,
        "engine_sha256": sha(engine),
        "checkpoint_sha256": sha(checkpoint),
        "profile_origin_unix": resource["origin_unix"],
        "profile_deadline_unix": resource["deadline_unix"],
        "full_acceptance": False,
    }
    campaign = Campaign(
        output, bindings, remaining, absolute_deadline=resource["deadline_unix"]
    )
    py = sys.executable
    failed = []
    try:
        campaign.run(
            "export-controls",
            [
                py,
                "-m",
                "tests.precision_export",
                "--engine",
                str(engine),
                "--checkpoint",
                str(checkpoint),
                "--output",
                str(output / "export"),
            ],
            90,
        )
        network = output / "export/selected-v4.cai"
        network_sha = sha(network)
        try:
            campaign.run(
                "numerical",
                [
                    py,
                    "-m",
                    "tools.network_audit",
                    "--engine",
                    str(engine),
                    "--network",
                    str(network),
                    "--checkpoint",
                    str(checkpoint),
                    "--export-format",
                    "4",
                    "--probes",
                    "100000",
                    "--seed",
                    "32452867",
                    "--maximum-error-cp",
                    "32",
                    "--max-seconds",
                    "600",
                    "--output",
                    str(output / "numerical"),
                ],
                610,
            )
        except StageFailure as error:
            observed = json.loads((output / "numerical/SUMMARY.json").read_text())
            if (
                error.record["exit"] != 1
                or observed.get("status") != "failed-frozen-error-bound"
                or observed.get("probes") != 100000
            ):
                raise
            failed.append("producer32cp numerical endpoint")
        try:
            campaign.run(
                "independent-numerical",
                [
                    py,
                    "-m",
                    "verification.numerical",
                    str(output / "numerical"),
                    "--engine",
                    str(engine),
                    "--network",
                    str(network),
                    "--checkpoint",
                    str(checkpoint),
                    "--protocol",
                    str(args.protocol.resolve()),
                    "--require-full",
                    "--max-seconds",
                    "600",
                    "--expected-network-sha256",
                    network_sha,
                    "--expected-checkpoint-sha256",
                    sha(checkpoint),
                ],
                610,
            )
        except StageFailure as error:
            observed = json.loads((output / "independent-numerical.log").read_text())
            if (
                error.record["exit"] != 1
                or observed.get("reason") != "frozen numerical error bound failed"
                or observed.get("observed", {}).get("probes") != 100000
            ):
                raise
            failed.append("independent32cp numerical endpoint")
        campaign.run(
            "restoration",
            [str(engine.parent / "network_test"), str(network), "1000000"],
            120,
        )
        if (
            sha(network) != network_sha
            or sha(engine) != bindings["engine_sha256"]
            or sha(checkpoint) != bindings["checkpoint_sha256"]
        ):
            raise ValueError("precision campaign immutable inputs changed")
        if sum(p.stat().st_size for p in output.rglob("*") if p.is_file()) > 2147483648:
            raise ValueError("precision campaign artifact byte ceiling exhausted")
        result = {
            "status": (
                "completed encoding and numerical experiment"
                if not failed
                else "completed encoding experiment with failed numerical gate"
            ),
            **bindings,
            "network_sha256": network_sha,
            "playing_strength_measured": False,
            "failed_domains": failed,
            "scope": "Higher-precision encoding only; no replacement of the active v3 network, strength actors or failed result",
        }
        (output / "PRECISION.json").write_text(json.dumps(result, indent=2) + "\n")
        campaign.close(
            (
                "passed numerical encoding domain"
                if not failed
                else "failed numerical encoding domain"
            ),
            result,
        )
        print(json.dumps(result))
        return 2 if failed else 0
    except BaseException as error:
        campaign.close("failed", {"error": repr(error), "full_acceptance": False})
        raise


if __name__ == "__main__":
    raise SystemExit(main())
