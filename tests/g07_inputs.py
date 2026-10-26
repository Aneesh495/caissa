"""Real small-corpus catalogs and immutable learning-file preparation controls.

No tensors are trained or evaluated. The incomplete full-learning fixture must
fail before it can emit a prepared input manifest or a full audit receipt.
"""

import argparse
import copy
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from tools.g07_inputs import (
    LearningPack,
    data_catalog,
    learning_catalog,
    metadata_sha,
    paired_inventory,
)
from verification.bundle import Bundle
from tools.campaign_process import atomic


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--corpus", type=Path, required=True)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    project = Path(__file__).resolve().parents[1]
    commit = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], text=True, timeout=5
    ).strip()
    guards = []

    def guard():
        guards.append(True)

    catalog = data_catalog(
        project,
        args.corpus,
        args.dataset,
        None,
        args.output / "data-catalog",
        commit,
        guard,
        diagnostic=True,
    )
    rule = json.loads(catalog.read_text())
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "verification.data_catalog",
            str(catalog),
            "--expected-catalog-sha256",
            metadata_sha(catalog),
            "--expected-commit",
            commit,
            "--input-root",
            str(project),
            "--output",
            str(project / rule["output"]),
            "--diagnostic",
        ],
        capture_output=True,
        text=True,
        timeout=135,
    )
    (args.output / "data-replay.log").write_text(result.stdout + result.stderr)
    observed = json.loads(result.stdout)
    assert (
        result.returncode == 0
        and observed["source_pairs"] == 50
        and observed["component_pass"] is False
    ), (observed, result.stderr)
    source_rows = json.loads((args.dataset / "SOURCE_PAIRS.json").read_text())
    expected = paired_inventory(source_rows, 50)
    prefix_rows = [{"path": name, "sha256": value} for name, value in expected.items()]
    assert paired_inventory(prefix_rows, 50) == expected
    controls = []
    for case in [
        "missing",
        "extra",
        "out-of-order",
        "boolean-identity",
        "bad-hash",
        "duplicate-path",
    ]:
        rows = copy.deepcopy(source_rows if case != "duplicate-path" else prefix_rows)
        if case == "missing":
            rows.pop()
        elif case == "extra":
            rows.append(rows[-1])
        elif case == "out-of-order":
            rows[0], rows[1] = rows[1], rows[0]
        elif case == "boolean-identity":
            rows[0]["pair"] = True
        elif case == "bad-hash":
            rows[0]["sha256"] = "invalid"
        else:
            rows[1]["path"] = rows[0]["path"]
        try:
            paired_inventory(rows, 50)
        except ValueError as error:
            controls.append({"case": case, "reason": str(error)})
        else:
            raise AssertionError("invalid original hash inventory admitted: " + case)

    with tempfile.TemporaryDirectory(prefix="caissa-learning-input-copy-") as folder:
        folder = Path(folder)
        original = folder / "original"
        original.mkdir()
        source = original / "original.bin"
        source.write_bytes(b"original immutable block\n" * 400000)
        digest = hashlib.sha256(source.read_bytes()).hexdigest()
        roots = {"one": original}
        pack = LearningPack(roots, folder / "pack", guard)
        try:
            reference = pack.add(
                "one", source.name, "raw/original.bin", digest, 16 * 1024**2
            )
            manifest = pack.finish(
                {"profile": "diagnostic-copy-only", "full_gate": False}
            )
            with Bundle(folder / "pack", 10) as bundle:
                bundle.verify_manifest()
                assert (
                    bundle.identities["raw/original.bin"]
                    == reference["sha256"]
                    == digest
                )
            for case, destination, expected_hash, maximum in [
                ("duplicate-target", "raw/original.bin", digest, 16 * 1024**2),
                ("escaping-target", "../escape", digest, 16 * 1024**2),
                ("wrong-original-hash", "wrong.bin", "0" * 64, 16 * 1024**2),
                ("short-byte-ceiling", "short.bin", digest, 1024),
            ]:
                try:
                    pack.add("one", source.name, destination, expected_hash, maximum)
                except ValueError as error:
                    controls.append({"case": case, "reason": str(error)})
                else:
                    raise AssertionError("invalid preparation copy admitted: " + case)
            rejected = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "verification.learning_bundle",
                    str(folder / "pack"),
                    "--expected-manifest-sha256",
                    manifest["manifest_sha256"],
                    "--expected-inputs-sha256",
                    manifest["inputs_sha256"],
                    "--output",
                    str(folder / "false-learning"),
                    "--maximum-seconds",
                    "10",
                ],
                capture_output=True,
                text=True,
                timeout=15,
            )
            assert (
                rejected.returncode == 1
                and json.loads(rejected.stdout)["full_gate"] is False
            )
            controls.append(
                {
                    "case": "copied-bytes-cannot-certify-learning",
                    "actual_exit": rejected.returncode,
                }
            )
        finally:
            pack.close()
        for case, source_roots, destination in [
            ("original-directory-preserved", roots, original / "unsafe"),
            (
                "aliased-original-roots",
                {"one": original, "two": original},
                folder / "aliased",
            ),
        ]:
            try:
                LearningPack(source_roots, destination, guard)
            except ValueError as error:
                controls.append({"case": case, "reason": str(error)})
            else:
                raise AssertionError("unsafe original directory use admitted")
        calls = []

        def expired():
            calls.append(True)
            raise TimeoutError("known preparation deadline")

        stopped = LearningPack(roots, folder / "stopped", expired)
        try:
            try:
                stopped.add("one", source.name, "never.bin", digest, 16 * 1024**2)
            except TimeoutError:
                assert not (folder / "stopped/never.bin").exists()
            else:
                raise AssertionError("expired preparation continued reading")
        finally:
            stopped.close()
        assert calls and hashlib.sha256(source.read_bytes()).hexdigest() == digest
        controls.append(
            {
                "case": "resource-guard-during-source-hashing",
                "original_bytes_unchanged": True,
            }
        )

        # Use the actual published identities and selected original checkpoint,
        # but deliberately omit the full training array. Preparation must stop.
        fake = folder / "incomplete-full"
        mappings = {
            "data/searched-full-v3-prepared/DATASET.json": "results/precision-v4-inputs/validation/DATASET.json",
            "config/protocol-v3.json": "config/protocol-v3.json",
            "config/protocol-v4.json": "config/protocol-v4.json",
            "runs/searched-full-model-v3/MODEL_CAMPAIGN.json": "results/full-model-v3-2026-10-25/MODEL_CAMPAIGN.json",
            "runs/searched-full-model-v3/selection/SELECTION.json": "results/full-model-v3-2026-10-25/SELECTION.json",
            "runs/searched-full-model-v3/selection/selected.pt": "results/precision-v4-inputs/selected.pt",
            "runs/searched-full-model-v3/selection/selected.cai": "results/full-model-v3-2026-10-25/selected.cai",
            "results/precision-v4-2026-10-25/selected-v4.cai": "results/precision-v4-2026-10-25/selected-v4.cai",
        }
        for target, source in mappings.items():
            path = fake / target
            path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(project / source, path)
        incomplete = fake / "runs/new-inputs/learning"
        try:
            learning_catalog(fake, incomplete, guard)
        except FileNotFoundError as error:
            assert "train-features.npy" in str(error), str(error)
            assert not (incomplete / "LEARNING_INPUTS.json").exists()
            assert not (incomplete / "MANIFEST.json").exists()
            controls.append(
                {
                    "case": "missing-full-training-array-cannot-create-prepared-learning-inputs"
                }
            )
        else:
            raise AssertionError("incomplete full learning originals admitted")

    # A full preparation command may not start during the strength handoff gap
    # or create a fresh scope based solely on a plausible source identifier.
    barrier = subprocess.run(
        [
            sys.executable,
            "-m",
            "tools.g07_inputs",
            "--checkout",
            str(project),
            "--expected-commit",
            commit,
        ],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert (
        barrier.returncode == 1
        and "strength pipeline is not settled" in json.loads(barrier.stdout)["reason"]
    )
    assert not (project / "runs/full-g07-inputs-v1").exists()
    atomic(
        args.output / "CONTROLS.json",
        {
            "status": "passed",
            "cases": controls,
            "real_original_pairs": 50,
            "streaming_copy_guard_calls": len(guards),
            "full_preparation_executed": False,
            "full_G07_certified": False,
            "full_acceptance": False,
        },
    )
    print(
        json.dumps(
            {
                "status": "passed",
                "actual_original_pairs": 50,
                "negative_controls": len(controls),
                "bounded_streaming_copy": True,
                "strength_handoff_priority": True,
                "full_G07_certified": False,
                "full_acceptance": False,
            }
        )
    )


if __name__ == "__main__":
    main()
