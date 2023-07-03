"""Actual diagnostic interruption, independent state replay and forgeries."""

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import torch

from tests.full_bundle import reference, fixture, seal as seal_full
from tests.source_binding import repository
from tools.campaign_process import atomic
from training.journal import recover
from verification.bundle import Bundle
from verification.learning import checkpoint
from verification.recovery_bundle import verify_training


def seal(folder):
    atomic(
        folder / "MANIFEST.json",
        {
            "files": {
                str(p.relative_to(folder)): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in sorted(folder.rglob("*"))
                if p.is_file() and p.name != "MANIFEST.json"
            }
        },
    )


def journal_controls(output):
    results = []
    for case in [
        "complete-tail",
        "torn-only",
        "missing-committed",
        "boolean-step",
        "unsafe-backup",
    ]:
        root = output / case
        root.mkdir()
        prefix = b'{"step":20,"loss":1}\n'
        tail = b'{"step":40,"loss":2}\n{"step":'
        raw = prefix + (b'{"step":' if case == "torn-only" else tail)
        if case == "missing-committed":
            raw = b'{"step":40}\n'
        if case == "boolean-step":
            raw = b'{"step":true}\n'
        (root / "observations.jsonl").write_bytes(raw)
        if case == "unsafe-backup":
            elsewhere = output / "outside"
            elsewhere.mkdir()
            (root / "recovery-tails").symlink_to(elsewhere, target_is_directory=True)
        try:
            value = recover(root, 20, 20)
        except ValueError as error:
            assert case in {"missing-committed", "boolean-step", "unsafe-backup"}, (
                case,
                error,
            )
            assert (root / "observations.jsonl").read_bytes() == raw
            results.append({"case": case, "rejected": str(error)})
        else:
            assert case in {"complete-tail", "torn-only"}
            assert (root / "observations.jsonl").read_bytes() == prefix
            assert (root / value["tail"]).read_bytes() == raw[len(prefix) :]
            assert recover(root, 20, 20) is None
            results.append(
                {
                    "case": case,
                    "exact_tail_preserved": True,
                    "second_recovery_noop": True,
                }
            )
    return results


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--engine", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    controls = journal_controls(args.output)
    producer = args.output / "producer"
    actual = subprocess.run(
        [
            sys.executable,
            "-m",
            "tools.training_recovery",
            "--engine",
            str(args.engine),
            "--output",
            str(producer),
        ],
        capture_output=True,
        text=True,
        timeout=190,
    )
    (args.output / "producer.log").write_text(actual.stdout + actual.stderr)
    logs = "\n".join(p.read_text()[-6000:] for p in producer.glob("*.log"))
    assert actual.returncode == 0, actual.stdout + actual.stderr + logs
    raw = producer / "evidence"
    config = json.loads((raw / "CONFIG.json").read_text())

    def run(label, folder, reason=None):
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "verification.training_recovery",
                str(folder),
                "--engine-sha256",
                config["engine_sha256"],
                "--source-commit",
                config["source_commit"],
            ],
            capture_output=True,
            text=True,
            timeout=65,
        )
        (args.output / (label + ".log")).write_text(result.stdout + result.stderr)
        value = json.loads(result.stdout)
        if reason is None:
            assert (
                result.returncode == 0
                and value["component_pass"] is True
                and value["full_G11_certified"] is False
            ), value
        else:
            assert result.returncode == 1 and reason in value["reason"], (label, value)
        controls.append(
            {"case": label, "actual_exit": result.returncode, "observed": value}
        )

    run("actual-kill-and-tensor-reconstruction", raw)
    with tempfile.TemporaryDirectory(prefix="caissa-training-bundle-") as temporary:
        temporary = Path(temporary)
        evidence = temporary / "evidence"
        shutil.copytree(raw, evidence / "training")
        identities = {
            str(p.relative_to(evidence)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in evidence.rglob("*")
            if p.is_file()
        }
        atomic(evidence / "MANIFEST.json", {"files": identities})
        inputs = {
            "engine": {"sha256": config["engine_sha256"]},
            "domains": {
                "G11": {
                    "source_commit": config["source_commit"],
                    "training_recovery": {
                        "config": reference(evidence, "training/CONFIG.json")
                    },
                    "artifacts": [
                        {"path": name, "sha256": digest}
                        for name, digest in identities.items()
                    ],
                }
            },
        }
        with Bundle(evidence, 120) as bundle:
            bundle.verify_manifest()
            value = verify_training(bundle, inputs, temporary / "replay")
            assert (
                value["component_pass"] is True and value["full_G11_certified"] is False
            )
        controls.append({"case": "immutable-component-stage", "observed": value})
    cases = [
        ("fake-kill", "actual forced SIGKILL"),
        ("boolean-signal", "actual forced SIGKILL"),
        ("changed-protected-generation", "protected committed generation"),
        ("changed-prefix", "committed journal prefix"),
        ("lost-tail", "exact removed bytes"),
        ("duplicate-observation", "duplicate, missing or torn"),
        ("missing-generation", "raw inventory"),
        ("extra-test-array", "raw inventory"),
        ("changed-objective", "scope, original resources"),
        ("changed-source", "source, program"),
        ("changed-optimizer", "tensor/state differs: optimizer"),
        ("changed-sampler", "exact original draws"),
        ("changed-rng", "tensor/state differs: torch_rng"),
    ]
    for label, reason in cases:
        with tempfile.TemporaryDirectory(
            prefix="caissa-training-forgery-"
        ) as temporary:
            folder = Path(temporary) / "raw"
            shutil.copytree(raw, folder)
            if label in {"fake-kill", "boolean-signal"}:
                p = folder / "KILL.json"
                value = json.loads(p.read_text())
                value["actual_exit" if label == "fake-kill" else "signal"] = (
                    0 if label == "fake-kill" else True
                )
                atomic(p, value)
            elif label == "changed-protected-generation":
                p = folder / "recovered/checkpoints/step-00000020.pt"
                p.write_bytes(p.read_bytes() + b"changed")
            elif label == "changed-prefix":
                p = folder / "recovered/observations.jsonl"
                rows = p.read_text().splitlines()
                rows[0] = rows[0].replace('"loss":', '"badloss":')
                p.write_text("\n".join(rows) + "\n")
            elif label == "lost-tail":
                next((folder / "recovered/recovery-tails").glob("*.bin")).write_bytes(
                    b"lost"
                )
            elif label == "duplicate-observation":
                p = folder / "recovered/observations.jsonl"
                p.write_bytes(
                    p.read_bytes() + p.read_bytes().splitlines(keepends=True)[-1]
                )
            elif label == "missing-generation":
                (folder / "whole/checkpoints/step-00000060.pt").unlink()
            elif label == "extra-test-array":
                (folder / "dataset/test-targets.npy").write_bytes(b"not admissible")
            elif label in {"changed-objective", "changed-source"}:
                p = folder / "CONFIG.json"
                value = json.loads(p.read_text())
                value[
                    "neural_weight" if label == "changed-objective" else "source_commit"
                ] = (20 if label == "changed-objective" else "0" * 40)
                atomic(p, value)
            else:
                p = folder / "recovered/checkpoints/step-00000100.pt"
                state = checkpoint(p)
                if label == "changed-optimizer":
                    state["optimizer"]["state"][0]["exp_avg"][0] += 0.01
                elif label == "changed-sampler":
                    state["sampler"]["state"]["state"] += 1
                elif label == "changed-rng":
                    state["torch_rng"][0] ^= 1
                torch.save(state, p)
                pointer = folder / "recovered/CHECKPOINTS.json"
                value = json.loads(pointer.read_text())
                for ref in [value["last"], value["best"]]:
                    if ref["path"] == "checkpoints/step-00000100.pt":
                        ref["sha256"] = hashlib.sha256(p.read_bytes()).hexdigest()
                atomic(pointer, value)
            seal(folder)
            run(label, folder, reason)
    with tempfile.TemporaryDirectory(prefix="caissa-training-full-entry-") as temporary:
        temporary = Path(temporary)
        source_tree = temporary / "source"
        commit = repository(source_tree)
        for label in [
            "saved-pass-cannot-certify-recovery",
            "rehashed-fake-kill-full-entry",
        ]:
            evidence = temporary / label
            inputs = fixture(
                evidence, Path(__file__).resolve().parents[1], source_tree, commit
            )
            domain = inputs["domains"]["G11"]
            domain["driver"] = "training-recovery-component-v1"
            if label == "saved-pass-cannot-certify-recovery":
                domain["training_recovery"] = {
                    "config": reference(evidence, "receipt.json")
                }
            else:
                shutil.copytree(raw, evidence / "training")
                p = evidence / "training/CONFIG.json"
                value = json.loads(p.read_text())
                value["source_commit"] = commit
                value["engine_sha256"] = inputs["engine"]["sha256"]
                atomic(p, value)
                p = evidence / "training/KILL.json"
                value = json.loads(p.read_text())
                value["actual_exit"] = 0
                atomic(p, value)
                seal(evidence / "training")
                domain["training_recovery"] = {
                    "config": reference(evidence, "training/CONFIG.json")
                }
                domain["artifacts"] = [
                    reference(evidence, str(p.relative_to(evidence)))
                    for p in (evidence / "training").rglob("*")
                    if p.is_file()
                ]
            digest = seal_full(evidence, inputs)
            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "verification.full_bundle",
                    str(evidence),
                    "--checkout",
                    str(source_tree),
                    "--expected-commit",
                    commit,
                    "--expected-inputs-sha256",
                    digest,
                    "--replay-output",
                    str(temporary / (label + "-replay")),
                    "--maximum-seconds",
                    "60",
                ],
                capture_output=True,
                text=True,
                timeout=65,
            )
            value = json.loads(result.stdout)
            assert result.returncode == 1 and value["full_acceptance"] is False, (
                label,
                value,
                result.stderr,
            )
            (args.output / (label + ".log")).write_text(result.stdout + result.stderr)
            controls.append(
                {"case": label, "actual_exit": result.returncode, "observed": value}
            )
    invalid = args.output / "full-campaign-barrier"
    rejected = subprocess.run(
        [
            sys.executable,
            "-m",
            "training.train",
            "unused",
            str(invalid),
            "--seed",
            "17",
            "--steps",
            "20000",
            "--recovery-barrier",
            str(invalid / "RECOVERY_READY.json"),
        ],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert (
        rejected.returncode == 2
        and "fixed100-step diagnostic" in rejected.stderr
        and not invalid.exists()
    )
    controls.append(
        {"case": "full-campaign-failpoint-refused", "actual_exit": rejected.returncode}
    )
    atomic(
        args.output / "CONTROLS.json",
        {"status": "passed", "controls": controls, "full_G11_certified": False},
    )
    print(
        json.dumps(
            {
                "status": "passed",
                "cases": len(controls),
                "actual_training_generations": 10,
                "full_G11_certified": False,
            }
        )
    )


if __name__ == "__main__":
    main()
