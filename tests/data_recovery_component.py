"""Actual killed data preparation, independent SQL replay and rehashed forgeries."""

import argparse
import hashlib
import json
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

from tools.campaign_process import atomic
from verification.bundle import Bundle
from verification.recovery_bundle import verify_data


def seal(root):
    atomic(
        root / "MANIFEST.json",
        {
            "files": {
                str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in sorted(root.rglob("*"))
                if p.is_file() and p != root / "MANIFEST.json"
            }
        },
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    producer = args.output / "producer"
    actual = subprocess.run(
        [sys.executable, "-B", "-m", "tools.data_recovery", "--output", str(producer)],
        capture_output=True,
        text=True,
        timeout=130,
    )
    (args.output / "producer.log").write_text(actual.stdout + actual.stderr)
    assert actual.returncode == 0, (
        actual.stdout
        + actual.stderr
        + "\n".join(p.read_text()[-4000:] for p in producer.glob("*.log"))
    )
    raw = producer / "evidence"
    config = json.loads((raw / "CONFIG.json").read_bytes())
    controls = []

    def run(label, folder, reason=None):
        result = subprocess.run(
            [
                sys.executable,
                "-B",
                "-m",
                "verification.data_recovery",
                str(folder),
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

    run("actual-sql-rollback-and-complete-splits", raw)
    cases = [
        ("fake-kill", "actual forced SIGKILL"),
        ("boolean-signal", "actual forced SIGKILL"),
        ("wrong-boundary", "data boundary"),
        ("wrong-progress", "data boundary"),
        ("changed-game", "original game pair"),
        ("changed-source", "original scope"),
        ("extra-file", "raw inventory"),
        ("lost-export", "raw inventory"),
        ("changed-target", "exported bytes differ"),
        ("changed-sql-target", "SQL positions differ"),
        ("lost-sql-contributor", "contributor lineage differs"),
        ("changed-final-contributor", "contributor provenance differs"),
    ]
    for label, reason in cases:
        with tempfile.TemporaryDirectory(prefix="caissa-data-forgery-") as temporary:
            folder = Path(temporary) / "raw"
            shutil.copytree(raw, folder)
            if label in {"fake-kill", "boolean-signal"}:
                p = folder / "KILL.json"
                value = json.loads(p.read_bytes())
                value["actual_exit" if label == "fake-kill" else "signal"] = (
                    0 if label == "fake-kill" else True
                )
                atomic(p, value)
            elif label in {"wrong-boundary", "wrong-progress"}:
                p = (
                    folder
                    / "boundary"
                    / (
                        "RECOVERY_READY.json"
                        if label == "wrong-boundary"
                        else "PREPARE_PROGRESS.json"
                    )
                )
                value = json.loads(p.read_bytes())
                value[
                    "committed_sources" if label == "wrong-boundary" else "source_pairs"
                ] = 31
                atomic(p, value)
            elif label == "changed-game":
                p = folder / "corpus/000000/000000000.json"
                value = json.loads(p.read_bytes())
                value["games"][0]["positions"][0]["score_stm"] += 1
                atomic(p, value)
            elif label == "changed-source":
                p = folder / "CONFIG.json"
                value = json.loads(p.read_bytes())
                value["source_commit"] = "0" * 40
                atomic(p, value)
            elif label == "extra-file":
                (folder / "fabricated.json").write_text("{}\n")
            elif label == "lost-export":
                (folder / "recovered/test-features.npy").unlink()
            elif label == "changed-target":
                p = folder / "recovered/train-targets.npy"
                value = bytearray(p.read_bytes())
                value[-1] ^= 1
                p.write_bytes(value)
            elif label in {"changed-sql-target", "lost-sql-contributor"}:
                p = folder / "boundary/identities.sqlite3"
                connection = sqlite3.connect(p)
                if label == "changed-sql-target":
                    connection.execute(
                        "UPDATE positions SET teacher_cp=teacher_cp+1 WHERE input=(SELECT min(input) FROM positions)"
                    )
                else:
                    connection.execute(
                        "DELETE FROM lineage WHERE input=(SELECT min(input) FROM lineage)"
                    )
                connection.commit()
                connection.close()
                Path(str(p) + "-wal").write_bytes(b"")
                Path(str(p) + "-shm").write_bytes(b"")
            elif label == "changed-final-contributor":
                for name in ["whole", "recovered"]:
                    p = folder / name / "train-identities.jsonl"
                    rows = p.read_text().splitlines()
                    value = json.loads(rows[0])
                    value["contributors"][0]["count"] += 1
                    rows[0] = json.dumps(value)
                    p.write_text("\n".join(rows) + "\n")
            seal(folder)
            run(label, folder, reason)
    with tempfile.TemporaryDirectory(prefix="caissa-data-bundle-") as temporary:
        temporary = Path(temporary)
        evidence = temporary / "evidence"
        shutil.copytree(raw, evidence / "data")
        seal(evidence)
        files = json.loads((evidence / "MANIFEST.json").read_bytes())["files"]
        inputs = {
            "domains": {
                "G11": {
                    "source_commit": config["source_commit"],
                    "data_recovery": {
                        "config": {
                            "path": "data/CONFIG.json",
                            "sha256": files["data/CONFIG.json"],
                        }
                    },
                    "artifacts": [{"path": n, "sha256": s} for n, s in files.items()],
                }
            }
        }
        with Bundle(evidence, 120) as bundle:
            bundle.verify_manifest()
            result = verify_data(bundle, inputs, temporary / "replay")
            assert result["component_pass"] and result["full_G11_certified"] is False
        controls.append(
            {"case": "immutable-full-bundle-component-stage", "observed": result}
        )
    result = {
        "status": "passed",
        "source_commit": config["source_commit"],
        "controls": controls,
        "full_G11_certified": False,
    }
    atomic(args.output / "VERIFICATION.json", result)
    print(
        json.dumps(
            {"status": "passed", "controls": len(controls), "full_G11_certified": False}
        )
    )


if __name__ == "__main__":
    main()
