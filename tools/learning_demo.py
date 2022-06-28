"""Run an original, finite three-seed learning and verification demonstration."""

import argparse
import hashlib
import json
import platform
import re
import shutil
import subprocess
import sys
from pathlib import Path

from tools.campaign_process import Campaign


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--engine", type=Path, default=Path("build/caissa"))
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args()
    if not re.fullmatch("[a-zA-Z0-9][a-zA-Z0-9_.-]{0,79}", args.run_id):
        parser.error("invalid noncolliding run identity")
    engine = args.engine.resolve()
    root = Path("runs") / args.run_id
    source = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    config = {
        "schema": "caissa-learning-demonstration-v1",
        "profile": "diagnostic",
        "source_commit": source,
        "uncommitted_source": bool(
            subprocess.check_output(["git", "status", "--porcelain"], text=True)
        ),
        "engine_sha256": sha(engine),
        "python": platform.python_version(),
        "code_sha256": {
            str(path): sha(path)
            for directory in ["training", "verification", "arena", "tests", "tools"]
            for path in sorted(Path(directory).glob("*.py"))
        },
        "workflow_sha256": sha(__file__),
        "process_owner_sha256": sha(Path(__file__).with_name("campaign_process.py")),
        "pairs": 200,
        "teacher_nodes": 2000,
        "seeds": [17, 41, 73],
        "steps": 100,
        "batch": 256,
        "threads": 2,
        "network_version": 3,
        "native_network_probes": 1000,
        "selection": "validation only; test arrays unopened",
        "maximum_campaign_seconds": 1800,
        "purpose": "exercise original generation, lineage preparation, learning and independent verification; no strength claim",
    }
    campaign = Campaign(root, config, 1800)
    try:
        frozen = root / "bin" / "caissa"
        frozen.parent.mkdir()
        shutil.copy2(engine, frozen)
        python = sys.executable

        def run(name, module, arguments, timeout):
            for path, expected in config["code_sha256"].items():
                if sha(path) != expected:
                    raise ValueError(
                        "campaign source changed during execution: " + path
                    )
            return campaign.run(
                name, [python, "-m", module, *map(str, arguments)], timeout
            )

        campaign.run("native-identity", [str(frozen.resolve()), "--version"], 10)
        run(
            "original-games",
            "training.corpus",
            [
                "--engine",
                frozen,
                "--output",
                root / "corpus",
                "--pairs",
                200,
                "--nodes",
                2000,
                "--workers",
                2,
                "--seed",
                19577,
                "--policy",
                "searched-v2",
                "--max-seconds",
                300,
                "--max-child-cpu-seconds",
                2400,
                "--max-gib",
                1,
                "--min-free-gib",
                1,
            ],
            330,
        )
        run("prepare", "training.prepare", [root / "corpus", root / "dataset"], 180)
        run(
            "independent-data",
            "verification.dataset",
            [root / "dataset", root / "corpus"],
            180,
        )
        run(
            "classical-baseline",
            "training.baselines",
            [root / "dataset", root / "baseline", "--engine", frozen],
            180,
        )
        seeds = [root / ("seed" + str(seed)) for seed in config["seeds"]]
        for seed, output in zip(config["seeds"], seeds):
            run(
                "train-" + str(seed),
                "training.train",
                [
                    root / "dataset",
                    output,
                    "--seed",
                    seed,
                    "--steps",
                    100,
                    "--batch",
                    256,
                    "--checkpoint-every",
                    50,
                    "--threads",
                    2,
                    "--network-version",
                    3,
                    "--baseline-directory",
                    root / "baseline",
                ],
                180,
            )
        run(
            "select",
            "training.select",
            [
                "--dataset",
                root / "dataset",
                "--runs",
                *seeds,
                "--output",
                root / "selection",
            ],
            60,
        )
        run(
            "independent-learning",
            "verification.learning",
            [
                "--dataset",
                root / "dataset",
                "--runs",
                *seeds,
                "--selection",
                root / "selection",
                "--baseline",
                root / "baseline",
                "--output",
                root / "INDEPENDENT.json",
            ],
            180,
        )
        run(
            "native-selected-network",
            "tools.network_audit",
            [
                "--engine",
                frozen,
                "--network",
                root / "selection/selected.cai",
                "--checkpoint",
                root / "selection/selected.pt",
                "--probes",
                1000,
                "--maximum-error-cp",
                32,
                "--output",
                root / "native-network",
            ],
            180,
        )
        # The mutation harness expects seeds and selection in one source folder.
        # It copies complete per-seed state without retraining or changing labels.
        run(
            "semantic-controls",
            "tests.learning_controls",
            [
                "--source",
                root,
                "--dataset",
                root / "dataset",
                "--baseline",
                root / "baseline",
                "--output",
                Path("runs") / (args.run_id + "-negative"),
            ],
            300,
        )
        for path, expected in config["code_sha256"].items():
            if sha(path) != expected:
                raise ValueError("campaign source changed during execution: " + path)
        campaign.close(
            "passed-diagnostic",
            {
                "independent": "INDEPENDENT.json",
                "negative_controls": "../" + args.run_id + "-negative/CONTROLS.json",
                "full_data_and_strength": "not exercised",
            },
        )
        print(
            json.dumps(
                {
                    "status": "passed",
                    "profile": "diagnostic",
                    "output": str(root),
                    "full_acceptance": False,
                }
            )
        )
        return 0
    except BaseException as error:
        campaign.close("failed", str(error))
        print(
            json.dumps(
                {
                    "status": "failed",
                    "reason": str(error),
                    "output": str(root),
                    "full_acceptance": False,
                }
            )
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
