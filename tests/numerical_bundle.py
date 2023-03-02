"""Rehashed G06 admission controls through the real full-verification CLI.

These fixtures do not contain a numerical probe campaign. Their admitted
metadata is never a numerical pass, and no PyTorch or native work is run.
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
from verification.numerical_bundle import admit


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    project = Path(__file__).resolve().parents[1]
    records = []
    with tempfile.TemporaryDirectory(prefix="caissa-numerical-bundle-") as temporary:
        temporary = Path(temporary)
        source = temporary / "source"
        commit = repository(source)
        original = temporary / "original"
        inputs = fixture(original, project, source, commit)
        shutil.copy2(project / "config/protocol-v4.json", original / "protocol.json")
        inputs["protocol"] = reference(original, "protocol.json")
        raw = original / "numerical"
        raw.mkdir()
        shutil.copy2(project / "config/precision-v4.json", raw / "PROFILE.json")
        shutil.copy2(
            project / "results/precision-v4-inputs/selected.pt", raw / "selected.pt"
        )
        (raw / "POSITIONS.fen").write_text("intentionally absent full probe work\n")
        (raw / "probes.jsonl").write_text("{}\n")
        identities = {
            "engine_sha256": inputs["engine"]["sha256"],
            "network_sha256": inputs["network"]["artifact"]["sha256"],
            "checkpoint_sha256": inputs["network"]["checkpoint_sha256"],
        }
        config = {
            "schema": "caissa-network-audit-v2",
            "trained": True,
            "generator": "standard-legal-walk-v1; terminal-or-ply>240-or-random<0.01 reset",
            "probes": 100000,
            "probe_seed": 32452867,
            "maximum_error_cp": 32,
            "maximum_seconds": 600,
            "error_contract": "unclamped-quantization-and-clamped-inference",
            "export_format": 4,
            "export_contract": "v3-float-to-v4-q4096-same-activation-ceiling-v1",
            "positions_sha256": reference(original, "numerical/POSITIONS.fen")[
                "sha256"
            ],
            **identities,
        }
        summary = {
            "probes": 100000,
            "probe_seed": 32452867,
            "positions_sha256": config["positions_sha256"],
            "probes_sha256": reference(original, "numerical/probes.jsonl")["sha256"],
            "status": "passed-frozen-error-bound",
            **identities,
        }
        write(raw / "CONFIG.json", config)
        write(raw / "SUMMARY.json", summary)
        names = {
            "profile": "PROFILE.json",
            "config": "CONFIG.json",
            "summary": "SUMMARY.json",
            "checkpoint": "selected.pt",
            "positions": "POSITIONS.fen",
            "observations": "probes.jsonl",
        }

        def bind(root, value):
            domain = value["domains"]["G06"]
            domain["driver"] = "numerical-probes-v1"
            domain["numerical"] = {
                key: reference(root, "numerical/" + name) for key, name in names.items()
            }
            domain["artifacts"] = list(domain["numerical"].values())
            return seal(root, value)

        bind(original, inputs)
        with Bundle(original, 20) as bundle:
            bundle.verify_manifest()
            paths, admitted, _ = admit(bundle, inputs)
            assert len(paths) == 6 and admitted["probes"] == 100000
        assert "torch" not in sys.modules
        records.append(
            {
                "case": "metadata-admission-only",
                "full_gate": False,
                "probe_rows_replayed": 0,
                "native_executions": 0,
            }
        )
        cases = {
            "short-sample": "complete frozen 100000-probe",
            "boolean-probes": "complete frozen 100000-probe",
            "changed-seed": "complete frozen 100000-probe",
            "weakened-error": "frozen numerical error bound",
            "clamped-only-error": "frozen numerical error bound",
            "changed-program": "producer inputs differ",
            "changed-checkpoint": "float checkpoint differs",
            "aliased-artifact": "distinct and declared",
            "undeclared-artifact": "distinct and declared",
            "changed-positions": "raw positions or observation identities differ",
            "false-summary-count": "producer sample summary differs",
            "unbounded-duration": "finite original ceiling",
            "changed-export-contract": "same-parameter export contract",
            "changed-profile-lattice": "profile differs from frozen deployment",
        }
        for case, expected in cases.items():
            root = temporary / case
            shutil.copytree(original, root)
            value = json.loads(json.dumps(inputs))
            changed_config = dict(config)
            changed_summary = dict(summary)
            if case in {"short-sample", "boolean-probes"}:
                changed_config["probes"] = 99999 if case == "short-sample" else True
            elif case == "changed-seed":
                changed_config["probe_seed"] += 1
            elif case == "weakened-error":
                changed_config["maximum_error_cp"] = 33
            elif case == "clamped-only-error":
                changed_config["error_contract"] = "clamped-only"
            elif case == "changed-program":
                changed_config["engine_sha256"] = "0" * 64
            elif case == "changed-checkpoint":
                (root / "numerical/selected.pt").write_bytes(b"another checkpoint\n")
            elif case == "changed-positions":
                path = root / "numerical/POSITIONS.fen"
                path.write_bytes(path.read_bytes() + b"changed\n")
            elif case == "false-summary-count":
                changed_summary["probes"] -= 1
            elif case == "unbounded-duration":
                changed_config["maximum_seconds"] = 3601
            elif case == "changed-export-contract":
                changed_config["export_contract"] = "other-float-semantics"
            elif case == "changed-profile-lattice":
                path = root / "numerical/PROFILE.json"
                profile = json.loads(path.read_text())
                profile["network"]["clip"] += 1
                write(path, profile)
            write(root / "numerical/CONFIG.json", changed_config)
            write(root / "numerical/SUMMARY.json", changed_summary)
            pin = bind(root, value)
            if case == "aliased-artifact":
                value["domains"]["G06"]["numerical"]["summary"] = value["domains"][
                    "G06"
                ]["numerical"]["config"]
                pin = seal(root, value)
            elif case == "undeclared-artifact":
                value["domains"]["G06"]["artifacts"] = value["domains"]["G06"][
                    "artifacts"
                ][:-1]
                pin = seal(root, value)
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
                "--replay-output",
                str(temporary / (case + "-replay")),
            ]
            run = subprocess.run(
                command,
                cwd=temporary,
                env=dict(os.environ, PYTHONPATH=str(project)),
                capture_output=True,
                text=True,
                timeout=25,
            )
            (args.output / (case + ".log")).write_text(run.stdout + run.stderr)
            actual = json.loads(run.stdout)
            assert run.returncode == 1 and expected in actual.get("reason", ""), (
                case,
                run.stdout,
                run.stderr,
            )
            records.append(
                {
                    "case": case,
                    "command": command,
                    "actual_exit": run.returncode,
                    "observed": actual,
                    "ordinary_hashes_recomputed": True,
                }
            )
    write(
        args.output / "CONTROLS.json",
        {
            "status": "passed",
            "controls": records,
            "full_numerical_sample_certified": False,
            "full_acceptance": False,
        },
    )
    print(
        json.dumps(
            {
                "status": "passed",
                "metadata_admissions": 1,
                "actual_full_cli_rejections": len(cases),
                "full_numerical_sample_certified": False,
                "full_acceptance": False,
            }
        )
    )


if __name__ == "__main__":
    main()
