"""Rehashed domain-relationship controls through the real full-verifier CLI.

The fixture contains metadata and an intentionally nonexecutable runtime. It
must remain incomplete even when every saved receipt claims success.
"""

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from tests.source_binding import repository, source_document


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n")


def reference(root, path):
    return {"path": path, "sha256": sha(root / path)}


def seal(root, inputs):
    write(root / "FULL_INPUTS.json", inputs)
    write(
        root / "MANIFEST.json",
        {
            "files": {
                str(p.relative_to(root)): sha(p)
                for p in sorted(root.rglob("*"))
                if p.is_file() and p.name != "MANIFEST.json"
            }
        },
    )
    return sha(root / "FULL_INPUTS.json")


def fixture(root, project, source, commit):
    root.mkdir()

    def copy(origin, name):
        (root / name).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(project / origin, root / name)
        return reference(root, name)

    dataset = copy(
        "results/precision-v4-inputs/validation/DATASET.json", "data/DATASET.json"
    )
    protocol = copy("config/protocol-v3.json", "protocol.json")
    selected = copy(
        "results/full-model-v3-2026-10-25/SELECTION.json", "learning/SELECTION.json"
    )
    seeds = {}
    for seed in [17, 41, 73]:
        seeds[str(seed)] = {
            "config": copy(
                f"results/full-model-v3-2026-10-25/seed{seed}/CONFIG.json",
                f"learning/seed{seed}/CONFIG.json",
            ),
            "checkpoints": copy(
                f"results/full-model-v3-2026-10-25/seed{seed}/CHECKPOINTS.json",
                f"learning/seed{seed}/CHECKPOINTS.json",
            ),
        }
    network = copy("results/precision-v4-2026-10-25/selected-v4.cai", "network.cai")
    heldout = {
        name: copy(name, "heldout/" + Path(name).name)
        for name in ["config/studies.json", "config/strength-openings.json"]
    }
    (root / "bin").mkdir()
    (root / "bin/caissa").write_bytes(
        b"intentionally not executable; metadata fixture only\n"
    )
    engine = reference(root, "bin/caissa")
    write(root / "receipt.json", {"status": "passed", "full_acceptance": True})
    write(root / "SOURCE_INPUTS.json", source_document(source, commit))
    inputs = {
        "schema": "caissa-full-inputs-v1",
        "source_commit": commit,
        "protocol": protocol,
        "engine": engine,
        "network": {
            "artifact": network,
            "checkpoint_sha256": "c76d8e9ef0f2255531bc9085f5d0330a7a4152cf9b21a65ff8aee740ab8b2005",
            "classical_contract": 1,
            "neural_weight": 10,
        },
        "dataset": {"metadata": dataset},
        "heldout": heldout,
        "learning": {"selection": selected, "seeds": seeds},
        "domains": {
            f"G{i:02d}": {
                "source_commit": commit,
                "engine_sha256": engine["sha256"],
                "network_sha256": network["sha256"],
                "status": "passed",
                "artifacts": [reference(root, "receipt.json")],
            }
            for i in range(1, 17)
        },
    }
    seal(root, inputs)
    return inputs


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    project = Path(__file__).resolve().parents[1]
    results = []
    with tempfile.TemporaryDirectory(prefix="caissa-full-graph-") as temporary:
        temporary = Path(temporary)
        source = temporary / "source"
        commit = repository(source)
        original = temporary / "original"
        baseline = fixture(original, project, source, commit)
        for case, reason in [
            ("receipt-booleans", None),
            ("changed-mixture", "selected mixture"),
            ("changed-checkpoint", "selected float checkpoint"),
            ("weakened-gain", "threshold"),
            ("lost-seed", "omitted or replaced"),
            ("test-selection", "test selection"),
            ("different-engine", "different engine"),
            ("different-evaluator", "different evaluator"),
            ("changed-heldout", "held-out"),
            ("bad-network-crc", "CRC"),
            ("linked-artifact-directory", None),
            ("missing-input-pin", "expected-inputs"),
            ("malformed-deployment", "must be an object"),
            ("bool-classical", "classical evaluation"),
            ("nonfinite-input", "nonfinite"),
        ]:
            root = temporary / case
            shutil.copytree(original, root)
            inputs = json.loads(json.dumps(baseline))
            if case == "malformed-deployment":
                inputs["network"] = None
            elif case == "bool-classical":
                inputs["network"]["classical_contract"] = True
            elif case == "nonfinite-input":
                inputs["nonfinite"] = float("inf")
            if case == "changed-mixture":
                inputs["network"]["neural_weight"] = 9
            elif case == "changed-checkpoint":
                inputs["network"]["checkpoint_sha256"] = "0" * 64
            elif case == "lost-seed":
                del inputs["learning"]["seeds"]["41"]
            elif case in {"different-engine", "different-evaluator"}:
                inputs["domains"]["G08"][
                    "engine_sha256" if case == "different-engine" else "network_sha256"
                ] = ("0" * 64)
            elif case == "weakened-gain":
                value = json.loads((root / "protocol.json").read_text())
                value["matches"]["minimum_neural_gain_elo"] = 49
                write(root / "protocol.json", value)
                inputs["protocol"] = reference(root, "protocol.json")
            elif case == "test-selection":
                value = json.loads((root / "learning/SELECTION.json").read_text())
                value["test_accessed"] = True
                write(root / "learning/SELECTION.json", value)
                inputs["learning"]["selection"] = reference(
                    root, "learning/SELECTION.json"
                )
            elif case == "changed-heldout":
                path = root / inputs["heldout"]["config/studies.json"]["path"]
                path.write_bytes(path.read_bytes() + b" \n")
                inputs["heldout"]["config/studies.json"] = reference(
                    root, str(path.relative_to(root))
                )
            elif case == "bad-network-crc":
                path = root / "network.cai"
                raw = bytearray(path.read_bytes())
                raw[-1] ^= 1
                path.write_bytes(raw)
                inputs["network"]["artifact"] = reference(root, "network.cai")
            pin = seal(root, inputs)
            if case == "linked-artifact-directory":
                outside = temporary / "outside-bin"
                shutil.move(str(root / "bin"), outside)
                (root / "bin").symlink_to(outside, target_is_directory=True)
            command = [
                sys.executable,
                "-m",
                "verification.verify",
                str(root),
                "--checkout",
                str(source),
                "--expected-commit",
                commit,
                "--profile",
                "full",
            ]
            if case != "missing-input-pin":
                command += ["--expected-inputs-sha256", pin]
            run = subprocess.run(
                command,
                cwd=temporary,
                env=dict(os.environ, PYTHONPATH=str(project)),
                capture_output=True,
                text=True,
                timeout=20,
            )
            value = json.loads(run.stdout)
            if case == "receipt-booleans":
                assert (
                    run.returncode == 2
                    and value["status"] == "incomplete"
                    and len(value["pending_semantic_gates"]) == 16
                ), (case, run.stdout, run.stderr)
                assert (
                    value["verified_relationships"]["learning"]["selected_seed"] == 73
                )
            else:
                assert run.returncode == 1 and value["status"] == "rejected", (
                    case,
                    run.stdout,
                    run.stderr,
                )
                if reason:
                    assert reason in value["reason"], (case, value)
            assert value.get("full_acceptance", False) is False
            results.append(
                {
                    "case": case,
                    "command": command,
                    "exit": run.returncode,
                    "observed": value,
                    "stderr": run.stderr,
                    "ordinary_hashes_and_external_input_pin_recomputed": case
                    != "missing-input-pin",
                }
            )
    report = {
        "status": "passed",
        "cases": results,
        "scope": "Synthetic metadata relationship controls through actual CLI; no raw domain gate certified or native executable run",
        "full_acceptance": False,
    }
    write(args.output / "CONTROLS.json", report)
    print(json.dumps(report))


if __name__ == "__main__":
    main()
