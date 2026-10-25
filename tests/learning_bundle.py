"""Original learning lineage and full-command raw-inventory controls.

No tensor checkpoint is loaded or evaluated. The positive case admits real
published metadata only; every full replay fixture intentionally lacks work.
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from tests.full_bundle import fixture, reference, seal, write
from tests.source_binding import repository
from verification.bundle import Bundle
from verification.learning_bundle import admit_lineage


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    project = Path(__file__).resolve().parents[1]
    records = []
    with tempfile.TemporaryDirectory(prefix="caissa-learning-bundle-") as temporary:
        temporary = Path(temporary)
        source = temporary / "source"
        commit = repository(source)
        original = temporary / "original"
        inputs = fixture(original, project, source, commit)
        shutil.copy2(project / "config/protocol-v4.json", original / "protocol.json")
        inputs["protocol"] = reference(original, "protocol.json")
        legacy = original / "legacy"
        legacy.mkdir()
        names = {
            "protocol": ("config/protocol-v3.json", "PROTOCOL.json"),
            "model_campaign": (
                "results/full-model-v3-2026-10-25/MODEL_CAMPAIGN.json",
                "MODEL_CAMPAIGN.json",
            ),
            "network": (
                "results/full-model-v3-2026-10-25/selected.cai",
                "original.cai",
            ),
            "checkpoint": ("results/precision-v4-inputs/selected.pt", "selected.pt"),
        }
        for origin, name in names.values():
            shutil.copy2(project / origin, legacy / name)

        def bind(root, value):
            domain = value["domains"]["G07"]
            domain["driver"] = "original-learning-v1"
            domain["original_learning"] = {
                key: reference(root, "legacy/" + name)
                for key, (_, name) in names.items()
            }
            domain["artifacts"] = [
                *domain["original_learning"].values(),
                value["learning"]["selection"],
            ]
            return seal(root, value)

        pin = bind(original, inputs)
        with Bundle(original, 20) as bundle:
            bundle.verify_manifest()
            _, _, model, lineage = admit_lineage(bundle, inputs)
            assert model["failed_domains"] and lineage["same_selected_float_checkpoint"]
            assert (
                lineage["original_network_sha256"] != lineage["deployed_network_sha256"]
            )
            assert lineage["new_learning_receipt_created"] is False
            assert lineage["full_gate"] is False
        assert "torch" not in sys.modules
        records.append(
            {
                "case": "real-original-lineage-only",
                "observed": lineage,
                "checkpoints_evaluated": 0,
                "full_gate": False,
            }
        )

        def run(case, root, value, pin, reason=None, replay=True):
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
            ]
            if replay:
                command += ["--replay-output", str(temporary / (case + "-replay"))]
            result = subprocess.run(
                command,
                cwd=temporary,
                env=dict(os.environ, PYTHONPATH=str(project)),
                capture_output=True,
                text=True,
                timeout=25,
            )
            (args.output / (case + ".log")).write_text(result.stdout + result.stderr)
            actual = json.loads(result.stdout)
            if reason:
                assert result.returncode == 1 and reason in actual.get("reason", ""), (
                    case,
                    result.stdout,
                    result.stderr,
                )
            else:
                assert result.returncode == 2 and actual["full_acceptance"] is False
                assert "G07" in actual["pending_semantic_gates"]
                assert not actual.get("verified_semantic_gates")
                assert not actual.get("verified_semantic_components")
            records.append(
                {
                    "case": case,
                    "command": command,
                    "actual_exit": result.returncode,
                    "observed": actual,
                    "ordinary_hashes_recomputed": True,
                }
            )

        run("metadata-is-not-full-gate", original, inputs, pin, replay=False)
        cases = {
            "rewritten-model-receipt": "original model_campaign identity differs",
            "replaced-original-protocol": "original protocol identity differs",
            "borrowed-deployment-network": "original learned export was replaced",
            "different-float-checkpoint": "selected float checkpoint differs",
            "rewritten-selection": "original validation-only selection identity differs",
            "changed-training-settings": "changed original learning section: training",
            "missing-raw-inventory": "full raw seed/dataset/baseline inventories required",
            "test-array-input": "test arrays are forbidden",
            "missing-seed": "full raw seed inventory differs",
            "missing-checkpoint": "full seed checkpoint chronology",
        }
        for case, reason in cases.items():
            root = temporary / case
            shutil.copytree(original, root)
            value = json.loads(json.dumps(inputs))
            if case == "rewritten-model-receipt":
                path = root / "legacy/MODEL_CAMPAIGN.json"
                model = json.loads(path.read_text())
                model.update(
                    network_sha256=value["network"]["artifact"]["sha256"],
                    failed_domains=[],
                    full_acceptance=True,
                )
                write(path, model)
            elif case == "replaced-original-protocol":
                shutil.copy2(root / "protocol.json", root / "legacy/PROTOCOL.json")
            elif case == "different-float-checkpoint":
                (root / "legacy/selected.pt").write_bytes(
                    b"different float parameters\n"
                )
            elif case == "rewritten-selection":
                path = root / value["learning"]["selection"]["path"]
                selection = json.loads(path.read_text())
                selection["criterion"] = "selected after matches"
                write(path, selection)
                value["learning"]["selection"] = reference(
                    root, str(path.relative_to(root))
                )
            elif case == "changed-training-settings":
                path = root / "protocol.json"
                protocol = json.loads(path.read_text())
                protocol["training"]["lr"] *= 2
                write(path, protocol)
                value["protocol"] = reference(root, "protocol.json")
            pin = bind(root, value)
            descriptor = value["domains"]["G07"]["original_learning"]
            if case == "borrowed-deployment-network":
                descriptor["network"] = value["network"]["artifact"]
                value["domains"]["G07"]["artifacts"].append(descriptor["network"])
            elif case in {"test-array-input", "missing-seed", "missing-checkpoint"}:
                placeholder = descriptor["checkpoint"]
                descriptor["dataset"] = {
                    name: placeholder
                    for name in [
                        "train-features.npy",
                        "validation-features.npy",
                        "validation-targets.npy",
                    ]
                }
                descriptor["baseline"] = {
                    name: placeholder
                    for name in [
                        "BASELINES.json",
                        "caissa",
                        "train-baseline.npy",
                        "validation-baseline.npy",
                    ]
                }
                descriptor["seeds"] = {}
                if case == "test-array-input":
                    descriptor["dataset"]["test-targets.npy"] = placeholder
                elif case == "missing-checkpoint":
                    for seed in ["17", "41", "73"]:
                        descriptor["seeds"][seed] = {
                            "initial": placeholder,
                            "initial_identity": placeholder,
                            "observations": placeholder,
                            "summary": placeholder,
                            "checkpoints": {
                                str(step): placeholder
                                for step in range(250, 20001, 250)
                            },
                        }
                    del descriptor["seeds"]["41"]["checkpoints"]["250"]
            pin = seal(root, value)
            run(case, root, value, pin, reason)
    write(
        args.output / "CONTROLS.json",
        {
            "status": "passed",
            "controls": records,
            "full_learning_component_certified": False,
            "full_gate": False,
            "full_acceptance": False,
        },
    )
    print(
        json.dumps(
            {
                "status": "passed",
                "original_lineage_admissions": 1,
                "metadata_only_full_command_remains_pending": True,
                "actual_full_cli_rejections": len(cases),
                "full_learning_component_certified": False,
                "full_acceptance": False,
            }
        )
    )


if __name__ == "__main__":
    main()
