"""Actual original CI data through bounded catalog staging and independent replay."""

import argparse
import fcntl
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from verification.data_catalog import DATASET_FILES, PARENT_DEADLINE, sha


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--corpus", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    project = Path(__file__).resolve().parents[1]
    args.output.mkdir(parents=True, exist_ok=False)
    commit = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=project, text=True, timeout=5
    ).strip()
    corpus, dataset = args.corpus.resolve(), args.dataset.resolve()
    pairs = json.loads((corpus / "SUMMARY.json").read_text())["pairs"]
    assert pairs == 50
    rule = {
        "schema": "caissa-original-data-catalog-v1",
        "status": "frozen",
        "profile": "diagnostic",
        "source_commit": commit,
        "dataset_sha256": sha(dataset / "DATASET.json"),
        "pairs": pairs,
        "output": str(
            (args.output / "real-small-original-data-replay")
            .resolve()
            .relative_to(project)
        ),
        "resources": {
            "maximum_wall_seconds": 120,
            "maximum_active_seconds": 120,
            "maximum_staging_seconds": 30,
            "maximum_input_gib": 1,
            "maximum_additional_gib": 1,
            "minimum_free_gib": 1,
            "maximum_attempts": 1,
            "parent_deadline_unix": None,
        },
        "shards": {},
        "files": {},
    }
    roots = {"corpus": corpus, "dataset": dataset, "config": project / "config"}

    def artifact(shard, name, destination):
        rule["files"][destination] = {
            "shard": shard,
            "path": name,
            "sha256": sha(roots[shard] / name),
        }

    for name in DATASET_FILES:
        artifact("dataset", name, "dataset/" + name)
    for name in ["CONFIG.json", "SUMMARY.json"]:
        artifact("corpus", name, "corpus/" + name)
    for number in range(pairs):
        name = f"{number//256:06d}/{number:09d}.json"
        artifact("corpus", name, "corpus/" + name)
    for name in ["studies.json", "strength-openings.json"]:
        artifact("config", name, "config/" + name)

    def manifests(value, folder):
        for key in value["shards"] or roots:
            source = roots[key]
            if key in value["shards"]:
                source = project / value["shards"][key]["root"]
            path = folder / (key + ".json")
            write(
                path,
                {
                    "schema": "caissa-input-view-v1",
                    "files": {
                        ref["path"]: ref["sha256"]
                        for ref in value["files"].values()
                        if ref["shard"] == key
                    },
                },
            )
            value["shards"][key] = {
                "root": str(source.relative_to(project)),
                "manifest": str(path.resolve().relative_to(project)),
                "manifest_sha256": sha(path),
            }

    manifests(rule, args.output / "manifests")
    original = args.output / "CATALOG.json"
    write(original, rule)
    records = []

    def run(name, value, reason=None, output=None, diagnostic=True, bind_output=True):
        path = args.output / (name + "-catalog.json")
        destination = output or (args.output / (name + "-replay"))
        value = json.loads(json.dumps(value))
        if bind_output:
            value["output"] = str(destination.resolve().relative_to(project))
        write(path, value)
        command = [
            sys.executable,
            "-m",
            "verification.data_catalog",
            str(path),
            "--expected-catalog-sha256",
            sha(path),
            "--expected-commit",
            commit,
            "--input-root",
            str(project),
            "--output",
            str(destination),
        ]
        if diagnostic:
            command.append("--diagnostic")
        result = subprocess.run(
            command, cwd=project, capture_output=True, text=True, timeout=135
        )
        (args.output / (name + ".log")).write_text(result.stdout + result.stderr)
        actual = json.loads(result.stdout)
        if reason:
            assert result.returncode == 1 and reason in actual.get("reason", ""), (
                name,
                result.stdout,
                result.stderr,
            )
        else:
            assert result.returncode == 0 and actual["status"] == "passed", (
                name,
                result.stdout,
                result.stderr,
            )
            assert (
                actual["profile"] == "diagnostic-data-replay"
                and actual["component_pass"] is False
            )
            assert (
                actual["full_gate"] is False
                and actual["dataset_sha256"] == rule["dataset_sha256"]
            )
        records.append(
            {
                "case": name,
                "command": command,
                "actual_exit": result.returncode,
                "observed": actual,
                "ordinary_hashes_recomputed": True,
            }
        )
        return destination

    completed = run("real-small-original-data", rule)
    run("existing-output-cannot-reset", rule, "scope cannot be reset", output=completed)
    run("different-output-cannot-reset", rule, "frozen output", bind_output=False)
    lock_path = project / "runs/TIMED_STRENGTH.lock"
    existed = lock_path.exists()
    with lock_path.open("a") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        run("timed-host-exclusion", rule, "timed decisive matches own the host")
        assert not (args.output / "timed-host-exclusion-replay").exists()
    if not existed:
        lock_path.unlink()
    for case, reason in {
        "renewed-budget": "cumulative resource ceilings differ",
        "full-promotion": "original frozen dataset or prefix",
        "omitted-pair": "inventory is missing or extra",
        "aliased-artifact": "reuses one input",
        "unsafe-source-path": "canonical relative",
        "swapped-array": "prepared array differs",
        "rehashed-wrong-source": "original input bytes differ",
        "extra-original-pair": "missing or additional paired games",
        "semantic-illegal-original-game": "independent original-data replay failed",
    }.items():
        value = json.loads(json.dumps(rule))
        if case == "renewed-budget":
            value["resources"]["maximum_wall_seconds"] += 1
        elif case == "full-promotion":
            value["profile"] = "full"
            value["pairs"] = 114791
            value["resources"] = {
                "maximum_wall_seconds": 21600,
                "maximum_active_seconds": 21600,
                "maximum_staging_seconds": 3600,
                "maximum_input_gib": 20,
                "maximum_additional_gib": 20,
                "minimum_free_gib": 10,
                "maximum_attempts": 1,
                "parent_deadline_unix": PARENT_DEADLINE,
            }
        elif case == "omitted-pair":
            del value["files"]["corpus/000000/000000000.json"]
        elif case == "aliased-artifact":
            value["files"]["dataset/validation-targets.npy"] = value["files"][
                "dataset/train-targets.npy"
            ]
        elif case == "unsafe-source-path":
            value["files"]["corpus/CONFIG.json"]["path"] = "../CONFIG.json"
        elif case == "swapped-array":
            first, second = (
                "dataset/validation-targets.npy",
                "dataset/train-targets.npy",
            )
            value["files"][first], value["files"][second] = (
                value["files"][second],
                value["files"][first],
            )
        elif case == "rehashed-wrong-source":
            value["files"]["corpus/000000/000000000.json"]["sha256"] = "0" * 64
            manifests(value, args.output / case / "manifests")
        elif case in {"extra-original-pair", "semantic-illegal-original-game"}:
            copied = (args.output / case / "source-corpus").resolve()
            shutil.copytree(corpus, copied)
            value["shards"]["corpus"]["root"] = str(copied.relative_to(project))
            path = copied / "000000/000000000.json"
            if case == "extra-original-pair":
                shutil.copy2(path, copied / "000000/000000999.json")
            else:
                game = json.loads(path.read_text())
                game["games"][0]["moves"][0] = "a1a8"
                write(path, game)
                value["files"]["corpus/000000/000000000.json"]["sha256"] = sha(path)
                copied_data = (args.output / case / "source-dataset").resolve()
                shutil.copytree(dataset, copied_data)
                value["shards"]["dataset"]["root"] = str(
                    copied_data.relative_to(project)
                )
                pairs_path = copied_data / "SOURCE_PAIRS.json"
                rows = json.loads(pairs_path.read_text())
                rows[0]["sha256"] = sha(path)
                write(pairs_path, rows)
                metadata_path = copied_data / "DATASET.json"
                metadata = json.loads(metadata_path.read_text())
                metadata["source_pairs_sha256"] = sha(pairs_path)
                write(metadata_path, metadata)
                for name in ["SOURCE_PAIRS.json", "DATASET.json"]:
                    value["files"]["dataset/" + name]["sha256"] = sha(
                        copied_data / name
                    )
                value["dataset_sha256"] = sha(metadata_path)
            manifests(value, args.output / case / "manifests")
        run(case, value, reason, diagnostic=case != "full-promotion")
        if case == "semantic-illegal-original-game":
            log = args.output / (case + "-replay/execution/independent.log")
            actual = json.loads(log.read_text())
            assert "illegal original game move" in actual["reason"], actual
    report = {
        "status": "passed",
        "cases": records,
        "full_data_component_certified": False,
        "full_gate": False,
        "full_acceptance": False,
    }
    write(args.output / "CONTROLS.json", report)
    print(
        json.dumps(
            {
                "status": "passed",
                "real_original_data_replays": 1,
                "actual_rejections": len(records) - 1,
                "full_data_component_certified": False,
                "full_acceptance": False,
            }
        )
    )


if __name__ == "__main__":
    main()
