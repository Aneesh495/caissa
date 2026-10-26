"""Bind the saved actor and unchanged tracked native inputs without executing it.

This is a source/input boundary, not proof of a compiler invocation, runtime
semantics, playing strength, full gate acceptance or external code originality.
"""

import argparse
import hashlib
import json
import os
import stat
import struct
import subprocess
import zlib
from pathlib import Path

from verification.bundle import digest_text, strict_json
from verification.source import (
    NATIVE,
    PRODUCT,
    inventory,
    require,
    selected,
    snapshot,
    verify_checkout,
)


def bounded(path, maximum):
    parts = Path(path).absolute().parts
    directory = os.open(parts[0], os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for part in parts[1:-1]:
            child = os.open(
                part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory
            )
            os.close(directory)
            directory = child
        descriptor = os.open(
            parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory
        )
    finally:
        os.close(directory)
    with os.fdopen(descriptor, "rb") as stream:
        before = os.fstat(stream.fileno())
        require(
            stat.S_ISREG(before.st_mode) and 0 < before.st_size <= maximum,
            "native binding input is linked, nonregular or excessive",
        )
        raw = stream.read(maximum + 1)
        after = os.fstat(stream.fileno())
    require(
        (
            before.st_dev,
            before.st_ino,
            before.st_size,
            before.st_mtime_ns,
            before.st_ctime_ns,
        )
        == (
            after.st_dev,
            after.st_ino,
            after.st_size,
            after.st_mtime_ns,
            after.st_ctime_ns,
        )
        and len(raw) == before.st_size,
        "native binding input changed during read",
    )
    return raw, hashlib.sha256(raw).hexdigest()


def inspect(
    checkout, commit, profile, profile_sha256, engine, network, learning_receipt
):
    checkout = Path(checkout).resolve()
    product = snapshot(checkout, commit, PRODUCT)
    verify_checkout(
        checkout,
        {
            "schema": "caissa-source-inputs-v2",
            "policy": PRODUCT,
            "commit": commit,
            "files": product,
        },
        commit,
        PRODUCT,
    )
    raw, observed_profile = bounded(profile, 4 * 1024**2)
    require(
        observed_profile
        == digest_text(profile_sha256)
        == product.get("config/protocol-v4.json"),
        "native binding profile differs from trusted committed experiment",
    )
    rule = strict_json(raw)
    require(
        isinstance(rule, dict)
        and rule.get("schema") == "caissa-experiment-protocol-v4"
        and rule.get("status") == "frozen",
        "native binding requires the frozen original v4 profile",
    )
    actor = rule["strength_actor"]
    require(isinstance(actor, dict), "native binding actor must be an object")
    require(
        type(actor["classical_contract"]) is int
        and actor["classical_contract"] == 1
        and type(actor["neural_weight"]) is int
        and actor["neural_weight"] == 10
        and actor["lazy_neural"] is True,
        "native binding changed classical, mixture or deferred contract",
    )
    for field in [
        "engine_sha256",
        "network_sha256",
        "checkpoint_sha256",
        "original_model_campaign_sha256",
    ]:
        digest_text(actor[field])
    compiled = actor["compiled_source_commit"]
    original_native = snapshot(checkout, compiled, NATIVE)
    final_native = snapshot(checkout, commit, NATIVE)
    original_modes = {b.name: b.mode for b in inventory(checkout, compiled, NATIVE)}
    final_modes = {b.name: b.mode for b in inventory(checkout, commit, NATIVE)}
    require(
        original_native == final_native and original_modes == final_modes,
        "native build input boundary changed since the saved actor source",
    )
    verify_checkout(checkout, {"commit": commit, "files": final_native}, commit, NATIVE)
    for name, mode in final_modes.items():
        require(
            bool((checkout / name).stat().st_mode & 0o111) == (mode == "100755"),
            "native source executable mode differs from trusted commit",
        )
    untracked = subprocess.run(
        ["git", "ls-files", "--others", "--exclude-standard", "-z"],
        cwd=checkout,
        capture_output=True,
        timeout=5,
        check=True,
    ).stdout
    require(
        len(untracked) <= 2 * 1024**2
        and not any(
            selected(name.decode("utf8"), NATIVE)
            for name in untracked.split(b"\0")
            if name
        ),
        "native boundary contains extra untracked inputs",
    )
    _, engine_sha = bounded(engine, 64 * 1024**2)
    wire, network_sha = bounded(network, 4 * 1024**2)
    require(
        engine_sha == actor["engine_sha256"] and network_sha == actor["network_sha256"],
        "native binding saved engine or network identity differs",
    )
    require(
        len(wire) >= 120
        and wire[:8] == b"CAISSAN4"
        and struct.unpack_from("<8I", wire, 8) == (4, 1, 12288, 64, 32, 16, 4096, 8188),
        "native binding network architecture or lattice differs",
    )
    length, flags, crc, baseline = struct.unpack_from("<4I", wire, 104)
    expected_payload = (
        12288 * 64 * 2
        + 64 * 4
        + 32 * 64 * 4
        + 32 * 4
        + 16 * 32 * 2
        + 16 * 4
        + 16 * 2
        + 4
    )
    require(
        length == expected_payload == len(wire) - 120
        and flags == 0
        and baseline == 1
        and zlib.crc32(wire[120:]) == crc
        and wire[40:104].decode("ascii") == actor["checkpoint_sha256"],
        "native binding selected checkpoint, payload or baseline differs",
    )
    receipt, receipt_sha = bounded(learning_receipt, 4 * 1024**2)
    require(
        receipt_sha == actor["original_model_campaign_sha256"],
        "native binding original learning receipt differs",
    )
    original = strict_json(receipt)
    require(
        isinstance(original, dict)
        and isinstance(original.get("failed_domains"), list)
        and all(isinstance(x, str) for x in original["failed_domains"])
        and original.get("checkpoint_sha256") == actor["checkpoint_sha256"]
        and original.get("protocol_sha256") == actor["original_protocol_sha256"]
        and original.get("test_model_metrics_used_for_selection") is False,
        "native binding original failed endpoints or unchanged selection differ",
    )
    return {
        "schema": "caissa-native-source-input-boundary-v1",
        "status": "metadata-boundary-admitted",
        "product_source_commit": commit,
        "compiled_source_commit": compiled,
        "profile_sha256": observed_profile,
        "engine_sha256": engine_sha,
        "network_sha256": network_sha,
        "checkpoint_sha256": actor["checkpoint_sha256"],
        "original_model_campaign_sha256": receipt_sha,
        "original_failed_domains": original["failed_domains"],
        "classical_contract": 1,
        "neural_weight": 10,
        "lazy_neural": True,
        "native_source_policy": NATIVE,
        "matched_native_files": len(final_native),
        "native_source_sha256": final_native,
        "native_source_modes": final_modes,
        "original_learning_receipt_unchanged": True,
        "runtime_replay_required": True,
        "compiler_environment_attribution_required": True,
        "external_source_similarity_audit_required": True,
        "full_gate": False,
        "full_acceptance": False,
    }


def verify_observation(bundle, inputs, checkout, commit):
    references = inputs["native_source_binding"]
    require(
        isinstance(references, dict)
        and set(references) == {"observation", "learning_receipt"},
        "native source binding reference inventory differs",
    )
    observed = bundle.json(bundle.reference(references["observation"]))
    receipt = bundle.reference(references["learning_receipt"])
    protocol = bundle.reference(inputs["protocol"])
    engine = bundle.reference(inputs["engine"])
    network = bundle.reference(inputs["network"]["artifact"])
    expected = inspect(
        checkout,
        commit,
        bundle.root / protocol,
        inputs["protocol"]["sha256"],
        bundle.root / engine,
        bundle.root / network,
        bundle.root / receipt,
    )
    from verification.draw_history import typed_equal

    require(
        typed_equal(observed, expected),
        "native source binding observation differs from actual trusted inputs",
    )
    return expected


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--checkout", type=Path, required=True)
    parser.add_argument("--expected-commit", required=True)
    parser.add_argument("--profile", type=Path, required=True)
    parser.add_argument("--expected-profile-sha256", required=True)
    parser.add_argument("--engine", type=Path, required=True)
    parser.add_argument("--network", type=Path, required=True)
    parser.add_argument("--learning-receipt", type=Path, required=True)
    args = parser.parse_args()
    try:
        print(
            json.dumps(
                inspect(
                    args.checkout,
                    args.expected_commit,
                    args.profile,
                    args.expected_profile_sha256,
                    args.engine,
                    args.network,
                    args.learning_receipt,
                )
            )
        )
    except (
        ValueError,
        OSError,
        KeyError,
        TypeError,
        subprocess.SubprocessError,
        struct.error,
        UnicodeDecodeError,
    ) as error:
        print(
            json.dumps(
                {
                    "status": "rejected",
                    "reason": str(error),
                    "full_gate": False,
                    "full_acceptance": False,
                }
            )
        )
        raise SystemExit(1)


if __name__ == "__main__":
    main()
