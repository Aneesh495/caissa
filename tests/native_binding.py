"""Source-bound CLI controls using a deliberately nonexecutable engine fixture.

No native process, compiler, model inference, browser or training is invoked.
The real published network and original failed learning receipt remain intact.
"""

import argparse
import copy
import hashlib
import json
import os
import shutil
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

from tests.full_bundle import fixture, reference, seal, sha, write
from tests.source_binding import repository

ENGINE = b"intentionally not executable; metadata fixture only\n"


def commit(root):
    subprocess.run(
        ["git", "add", "-A"], cwd=root, check=True, capture_output=True, timeout=5
    )
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=fixture",
            "-c",
            "user.email=fixture@invalid",
            "commit",
            "-qm",
            "metadata fixture",
        ],
        cwd=root,
        check=True,
        capture_output=True,
        timeout=5,
    )
    return subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=root, text=True, timeout=5
    ).strip()


def invoke(command, temporary, project):
    run = subprocess.run(
        [sys.executable, "-m", *command],
        cwd=temporary,
        env=dict(os.environ, PYTHONPATH=str(project)),
        capture_output=True,
        text=True,
        timeout=25,
    )
    value = json.loads(run.stdout)
    assert value.get("full_acceptance") is False, value
    return {
        "exit": run.returncode,
        "command": command,
        "observed": value,
        "stderr": run.stderr,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    project = Path(__file__).resolve().parents[1]
    controls = []
    with tempfile.TemporaryDirectory(prefix="caissa-native-binding-") as temporary:
        temporary = Path(temporary).resolve()
        baseline = temporary / "baseline"
        compiled = repository(baseline)
        original = json.loads((project / "config/protocol-v4.json").read_text())
        original["strength_actor"].update(
            engine_sha256=hashlib.sha256(ENGINE).hexdigest(),
            compiled_source_commit=compiled,
        )
        write(baseline / "config/protocol-v4.json", original)
        (baseline / "web/index.html").write_text(
            "<title>metadata-only UI revision</title>\n"
        )
        final = commit(baseline)
        for case in [
            "unchanged-native-ui-revision",
            "committed-native-edit",
            "committed-header-addition",
            "committed-cmake-asset",
            "committed-app-asset",
            "committed-test-cpp",
            "committed-source-removal",
            "committed-native-mode",
            "committed-native-link",
            "dirty-native",
            "dirty-native-mode",
            "untracked-native",
            "wrong-product-commit",
            "wrong-compiled-commit",
            "wrong-profile-pin",
            "replaced-engine",
            "replaced-network",
            "replaced-original-receipt",
            "linked-engine",
            "changed-classical",
            "changed-mixture",
            "changed-lazy",
            "changed-selected-checkpoint",
            "changed-wire-crc",
            "changed-wire-length",
        ]:
            root = temporary / case
            root.mkdir()
            source = root / "source"
            shutil.copytree(baseline, source)
            engine, network, receipt = (
                root / "engine",
                root / "network.cai",
                root / "MODEL_CAMPAIGN.json",
            )
            engine.write_bytes(ENGINE)
            shutil.copy2(
                project / "results/precision-v4-2026-10-25/selected-v4.cai", network
            )
            shutil.copy2(
                project / "results/full-model-v3-2026-10-25/MODEL_CAMPAIGN.json",
                receipt,
            )
            profile = source / "config/protocol-v4.json"
            rule = copy.deepcopy(original)
            expected = final
            if case == "committed-native-edit" or case == "dirty-native":
                (source / "src/main.cpp").write_text("int main(){return 1;}\n")
            elif case in {
                "committed-header-addition",
                "committed-cmake-asset",
                "committed-app-asset",
                "committed-test-cpp",
                "untracked-native",
            }:
                name = {
                    "committed-header-addition": "include/new.hh",
                    "committed-cmake-asset": "cmake/options.txt",
                    "committed-app-asset": "apps/embedded.json",
                    "committed-test-cpp": "tests/new.cpp",
                    "untracked-native": "src/new.inc",
                }[case]
                path = source / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"unreviewed native build input\n")
            elif case == "committed-source-removal":
                (source / "src/main.cpp").unlink()
            elif case in {"committed-native-mode", "dirty-native-mode"}:
                (source / "src/main.cpp").chmod(0o755)
            elif case == "committed-native-link":
                path = source / "src/main.cpp"
                path.unlink()
                path.symlink_to("../include/core.h")
            elif case == "wrong-product-commit":
                expected = compiled
            elif case == "wrong-compiled-commit":
                rule["strength_actor"]["compiled_source_commit"] = "0" * 40
            elif case == "replaced-engine":
                engine.write_bytes(ENGINE + b"changed\n")
            elif case == "replaced-network":
                network.write_bytes(network.read_bytes() + b"changed")
            elif case == "replaced-original-receipt":
                value = json.loads(receipt.read_text())
                value["failed_domains"] = []
                write(receipt, value)
            elif case == "linked-engine":
                outside = root / "outside"
                engine.rename(outside)
                engine.symlink_to(outside)
            elif case.startswith("changed-"):
                field, value = {
                    "changed-classical": ("classical_contract", True),
                    "changed-mixture": ("neural_weight", 20),
                    "changed-lazy": ("lazy_neural", False),
                    "changed-selected-checkpoint": ("checkpoint_sha256", "0" * 64),
                    "changed-wire-crc": ("network_sha256", None),
                    "changed-wire-length": ("network_sha256", None),
                }[case]
                if case.startswith("changed-wire-"):
                    raw = bytearray(network.read_bytes())
                    if case.endswith("crc"):
                        raw[-1] ^= 1
                    else:
                        struct.pack_into("<I", raw, 104, len(raw) - 121)
                    network.write_bytes(raw)
                    value = sha(network)
                rule["strength_actor"][field] = value
            if case.startswith("committed-"):
                expected = commit(source)
            if json.dumps(rule, sort_keys=True) != json.dumps(original, sort_keys=True):
                write(profile, rule)
                expected = commit(source)
            pin = "0" * 64 if case == "wrong-profile-pin" else sha(profile)
            command = [
                "verification.runtime_binding",
                "--checkout",
                str(source),
                "--expected-commit",
                expected,
                "--profile",
                str(profile),
                "--expected-profile-sha256",
                pin,
                "--engine",
                str(engine),
                "--network",
                str(network),
                "--learning-receipt",
                str(receipt),
            ]
            result = invoke(command, temporary, project)
            with (args.output / "OBSERVATIONS.jsonl").open("a") as stream:
                stream.write(json.dumps({"case": case, **result}) + "\n")
            assert result["exit"] == (
                0 if case == "unchanged-native-ui-revision" else 1
            ), (case, result)
            if case == "unchanged-native-ui-revision":
                admitted = result["observed"]
                assert (
                    admitted["compiled_source_commit"] == compiled
                    and admitted["product_source_commit"] == final
                )
                assert (
                    admitted["original_failed_domains"]
                    == json.loads(receipt.read_text())["failed_domains"]
                )
                assert (
                    admitted["matched_native_files"] == 3
                    and admitted["full_gate"] is False
                )
                for name in [
                    "runtime_replay_required",
                    "compiler_environment_attribution_required",
                    "external_source_similarity_audit_required",
                ]:
                    assert admitted[name] is True
                for name, identity in admitted["native_source_sha256"].items():
                    raw = subprocess.check_output(
                        ["git", "show", compiled + ":" + name], cwd=source, timeout=5
                    )
                    assert hashlib.sha256(raw).hexdigest() == identity
                positive_source = source
                positive_receipt = receipt
                positive = admitted
            else:
                assert (
                    result["observed"]["status"] == "rejected"
                    and result["observed"]["reason"]
                )
            controls.append({"case": case, **result})

        evidence = temporary / "full-entry"
        inputs = fixture(evidence, project, positive_source, final)
        shutil.copy2(
            positive_source / "config/protocol-v4.json", evidence / "protocol.json"
        )
        shutil.copy2(positive_receipt, evidence / "learning/MODEL_CAMPAIGN.json")
        write(evidence / "NATIVE_BOUNDARY.json", positive)
        inputs["protocol"] = reference(evidence, "protocol.json")
        inputs["native_source_binding"] = {
            "observation": reference(evidence, "NATIVE_BOUNDARY.json"),
            "learning_receipt": reference(evidence, "learning/MODEL_CAMPAIGN.json"),
        }
        for case in [
            "full-entry-boundary-still-incomplete",
            "full-entry-forged-pass",
            "full-entry-omitted-failure",
            "full-entry-forged-source-map",
            "full-entry-runtime-waived",
            "full-entry-legacy-no-boundary",
        ]:
            value = copy.deepcopy(inputs)
            observation = copy.deepcopy(positive)
            if case == "full-entry-forged-pass":
                observation["full_gate"] = True
            elif case == "full-entry-omitted-failure":
                observation["original_failed_domains"] = []
            elif case == "full-entry-forged-source-map":
                observation["native_source_sha256"]["src/main.cpp"] = "0" * 64
            elif case == "full-entry-runtime-waived":
                observation["runtime_replay_required"] = False
            elif case == "full-entry-legacy-no-boundary":
                del value["native_source_binding"]
            write(evidence / "NATIVE_BOUNDARY.json", observation)
            if "native_source_binding" in value:
                value["native_source_binding"]["observation"] = reference(
                    evidence, "NATIVE_BOUNDARY.json"
                )
            pin = seal(evidence, value)
            result = invoke(
                [
                    "verification.full_bundle",
                    str(evidence),
                    "--checkout",
                    str(positive_source),
                    "--expected-commit",
                    final,
                    "--expected-inputs-sha256",
                    pin,
                ],
                temporary,
                project,
            )
            with (args.output / "OBSERVATIONS.jsonl").open("a") as stream:
                stream.write(json.dumps({"case": case, **result}) + "\n")
            incomplete = case in {
                "full-entry-boundary-still-incomplete",
                "full-entry-legacy-no-boundary",
            }
            assert result["exit"] == (2 if incomplete else 1), (case, result)
            if incomplete:
                assert len(result["observed"]["pending_semantic_gates"]) == 16
                assert (
                    "native_source_boundary"
                    in result["observed"]["verified_relationships"]
                ) == (case != "full-entry-legacy-no-boundary")
            else:
                assert (
                    "native source binding observation differs"
                    in result["observed"]["reason"]
                )
            controls.append(
                {
                    "case": case,
                    "ordinary_manifest_and_external_input_hashes_recomputed": True,
                    **result,
                }
            )

    report = {
        "status": "passed",
        "controls": controls,
        "control_count": len(controls),
        "native_or_model_execution": False,
        "engine_fixture_executable": False,
        "full_gate": False,
        "full_acceptance": False,
    }
    write(args.output / "CONTROLS.json", report)
    print(json.dumps({k: v for k, v in report.items() if k != "controls"}))


if __name__ == "__main__":
    main()
