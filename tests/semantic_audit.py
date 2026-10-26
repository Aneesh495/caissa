"""Actual combined G14 witnesses and rehashed full-entry semantic controls.

Four fixed mate games are isolated diagnostics, never strength observations.
No training, model selection, browser or prior full-domain campaign is run.
"""

import argparse
import copy
import contextlib
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

from tests.full_bundle import fixture, reference, sha, write
from tools.host_lease import ENVIRONMENT, HostLease
from tools.semantic_witness import capture
from verification.semantic_audit import mutate


def seal(root, inputs):
    write(root / "FULL_INPUTS.json", inputs)
    write(
        root / "MANIFEST.json",
        {
            "files": {
                str(p.relative_to(root)): sha(p)
                for p in sorted(root.rglob("*"))
                if p.is_file() and p != root / "MANIFEST.json"
            }
        },
    )
    return sha(root / "FULL_INPUTS.json")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--engine", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output = args.output.resolve()
    args.output.mkdir(parents=True, exist_ok=False)
    project = Path(__file__).resolve().parents[1]
    scope = json.loads(
        (project / "config/semantic-audit-development-v1.json").read_text()
    )
    assert time.time() < scope["deadline_unix"]
    results = []
    with contextlib.closing(HostLease(project / "runs")) as lease:
        os.environ[ENVIRONMENT] = str(lease.stream.fileno())
        positive = args.output / "original-witness"
        observed = capture(
            args.engine,
            project / "results/precision-v4-2026-10-25/selected-v4.cai",
            project / "config/semantic-audit-v1.json",
            positive,
        )
        write(args.output / "PRODUCER.json", observed)
        head = observed["source_commit"]
        original = args.output / "original-full"
        inputs = fixture(original, project, project, head)
        shutil.copy2(project / "config/protocol-v4.json", original / "protocol.json")
        shutil.copy2(args.engine, original / "bin/caissa")
        inputs["protocol"] = reference(original, "protocol.json")
        inputs["engine"] = reference(original, "bin/caissa")
        for domain in inputs["domains"].values():
            domain["engine_sha256"] = inputs["engine"]["sha256"]
        shutil.copytree(positive, original / "g14")
        domain = inputs["domains"]["G14"]
        domain.update(
            driver="semantic-audit-v1",
            semantic_audit={"config": reference(original, "g14/CONFIG.json")},
            artifacts=[
                reference(original, str(p.relative_to(original)))
                for p in sorted((original / "g14").rglob("*"))
                if p.is_file()
            ],
        )
        seal(original, inputs)
        for case in [
            "positive-full-entry",
            "missing-replay-output",
            "illegal-pv",
            "swapped-result-colors",
            "mismatched-network-inference",
            "incorrect-draw-claim",
            "undeclared-raw-artifact",
        ]:
            lease.check()
            root = args.output / case
            shutil.copytree(original, root)
            value = copy.deepcopy(inputs)
            if case in [
                "illegal-pv",
                "swapped-result-colors",
                "mismatched-network-inference",
                "incorrect-draw-claim",
            ]:
                mutate(root / "g14", case, 0)
                value["domains"]["G14"]["artifacts"] = [
                    reference(root, str(p.relative_to(root)))
                    for p in sorted((root / "g14").rglob("*"))
                    if p.is_file()
                ]
            elif case == "undeclared-raw-artifact":
                value["domains"]["G14"]["artifacts"] = [
                    ref
                    for ref in value["domains"]["G14"]["artifacts"]
                    if ref["path"] != "g14/WITNESSES.json"
                ]
            pin = seal(root, value)
            command = [
                sys.executable,
                "-B",
                "-m",
                "verification.full_bundle",
                str(root),
                "--checkout",
                str(project),
                "--expected-commit",
                head,
                "--expected-inputs-sha256",
                pin,
                "--maximum-seconds",
                "240",
            ]
            if case != "missing-replay-output":
                command += ["--replay-output", str(args.output / (case + "-replay"))]
            run = subprocess.run(
                command,
                cwd=project,
                capture_output=True,
                text=True,
                timeout=260,
                pass_fds=(lease.stream.fileno(),),
            )
            result = json.loads(run.stdout)
            write(
                args.output / (case + "-RESULT.json"),
                {
                    "command": command,
                    "exit": run.returncode,
                    "stdout": result,
                    "stderr": run.stderr,
                    "ordinary_manifest_and_external_pin_recomputed": True,
                },
            )
            assert result["full_acceptance"] is False
            if case == "positive-full-entry":
                assert run.returncode == 2, result
                saved_image = (
                    observed["engine_sha256"]
                    == "1ff25a97b2272f589aac40049f9c76e53228a3682f64489c72566dae449a9897"
                )
                if saved_image:
                    replay = result["verified_semantic_gates"]["G14"]
                    assert (
                        replay["full_gate"] is True
                        and len(result["pending_semantic_gates"]) == 15
                    )
                else:
                    replay = result["verified_semantic_components"]["G14"]
                    assert (
                        replay["full_gate"] is False
                        and len(result["pending_semantic_gates"]) == 16
                    )
                assert len(replay["rehashed_semantic_rejections"]) == 16
            elif case == "missing-replay-output":
                assert (
                    run.returncode == 2 and len(result["pending_semantic_gates"]) == 16
                ), result
            else:
                assert run.returncode == 1 and result["status"] == "rejected", result
                reason = {
                    "illegal-pv": "illegal semantic PV",
                    "swapped-result-colors": "swapped result colors",
                    "mismatched-network-inference": "mismatched network inference",
                    "incorrect-draw-claim": "incorrect draw claim",
                    "undeclared-raw-artifact": "G14 raw inventory",
                }[case]
                assert reason in result["reason"], result
            results.append({"case": case, "exit": run.returncode})
        report = {
            "status": "passed",
            "source_commit": head,
            "engine_sha256": observed["engine_sha256"],
            "network_sha256": observed["network_sha256"],
            "semantic_rehashed_rejections": 16,
            "full_entry_cases": results,
            "diagnostic_games": 4,
            "strength_games": 0,
            "training": False,
            "browser": False,
            "full_G14_saved_image_sample": saved_image,
            "full_acceptance": False,
        }
        write(args.output / "CONTROLS.json", report)
        print(json.dumps(report))
        del os.environ[ENVIRONMENT]


if __name__ == "__main__":
    main()
