"""Explicit derived-runtime strength contract, preserving the real learning run.

No learning receipt is synthesized and no completed phase is restarted. The
new actor is a saved original search image plus the already validated integer
encoding of the same validation-selected float checkpoint.
"""

import hashlib
import json
import math
import struct
import zlib
from pathlib import Path

from tools.full_learning import frozen_rule as original_rule
from tools.full_strength import configuration as original_configuration
from tools.power_guard import BATTERY_POLICY
from verification.bundle import strict_json
from verification.draw_history import typed_equal
from verification.source import PRODUCT, inventory
from verification.strength import full_actor_options

ORIGINAL_PROTOCOL = "4cf0545699ab141dafe4e3f67fcbdb7b996cbec2b8e0b246fc2137a5dc963f62"
MODEL_RECEIPT = "92d62149d3a4de184ad93b9f5f04f77e38386992d04d02bd824b33cf3e5241bd"
SELECTION = "1cd49b3062986086e74396fce27fbbdf4886a0ce9b5b6b6350533b27e3ac8b84"
INDEPENDENT_LEARNING = (
    "19e2b2d26bc1b76f16c466519737f87dd4a1a3ff0d0102656208bc33f5aaa20b"
)
WIRE_EXPORT = "50d46da414a85fadefa0aba85201d11caf51187fda943e02eafc33a5f034f736"
CHECKPOINT = "c76d8e9ef0f2255531bc9085f5d0330a7a4152cf9b21a65ff8aee740ab8b2005"
NETWORK = "52d0306143392ad683c3ebb09fe013f34e1f9e2bc44d3aa153b32314207374b7"
ENGINE = "1ff25a97b2272f589aac40049f9c76e53228a3682f64489c72566dae449a9897"
COMPILED_SOURCE = "5803cc485420b19eb96dda2c29f81fcfc6b09b6b"
OPENINGS = "61b8c8812a107e0ea0b6e8a763a0d52d088b6b8480a0879a4952c4689bae71a8"
PARENT_DEADLINE = 1793150297.974828
SCOPES = {
    "neural": "runs/full-neural-strength-v4",
    "external": "runs/full-external-strength-v4",
}


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def require(condition, reason):
    if not condition:
        raise ValueError(reason)


def document(path, maximum=4 * 1024 * 1024):
    path = Path(path)
    require(
        path.is_file() and not path.is_symlink() and 0 < path.stat().st_size <= maximum,
        "v4 metadata missing, linked or excessive",
    )
    return strict_json(path.read_bytes())


def frozen_profile(path, expected_sha, root):
    require(sha(path) == expected_sha, "v4 profile external identity differs")
    rule = document(path)
    require(
        rule.get("schema") == "caissa-experiment-protocol-v4"
        and rule.get("status") == "frozen",
        "v4 profile is not frozen",
    )
    base = original_rule(Path(root) / "config/protocol-v3.json", ORIGINAL_PROTOCOL)
    for section in [
        "data",
        "training",
        "model_campaign",
        "matches",
        "selection",
        "classical_control",
    ]:
        require(
            typed_equal(rule.get(section), base[section]),
            "v4 changed original learning, control or match contract: " + section,
        )
    expected_network = {
        **base["network"],
        "format": 4,
        "scale": 4096,
        "clip": 8188,
        "probe_seed": 32452867,
    }
    require(
        typed_equal(rule.get("network"), expected_network),
        "v4 encoding, mixture or error contract differs",
    )
    require(
        typed_equal(
            rule.get("search_optimizations"),
            {**base["search_optimizations"], "deferred_neural_state": True},
        ),
        "v4 exact search optimization contract differs",
    )
    require(
        typed_equal(
            rule.get("strength_actor"),
            {
                "engine_sha256": ENGINE,
                "compiled_source_commit": COMPILED_SOURCE,
                "network_sha256": NETWORK,
                "checkpoint_sha256": CHECKPOINT,
                "original_model_campaign_sha256": MODEL_RECEIPT,
                "original_selection_sha256": SELECTION,
                "original_independent_learning_sha256": INDEPENDENT_LEARNING,
                "wire_export_sha256": WIRE_EXPORT,
                "original_protocol_sha256": ORIGINAL_PROTOCOL,
                "openings_sha256": OPENINGS,
                "classical_contract": 1,
                "selected_seed": 73,
                "selected_step": 2750,
                "neural_weight": 10,
                "lazy_neural": True,
            },
        ),
        "v4 immutable actor/selection derivation differs",
    )
    require(
        typed_equal(
            rule.get("strength_resources"),
            {
                "maximum_attempts": 3,
                "maximum_active_seconds_per_domain": 43200,
                "maximum_wall_seconds_per_domain": 43200,
                "minimum_free_gib": 10,
                "maximum_additional_gib_per_domain": 20,
                "parent_project_deadline_unix": PARENT_DEADLINE,
                "host_policy": BATTERY_POLICY,
                "scope_paths": SCOPES,
            },
        ),
        "v4 cumulative resources, scope paths or original parent deadline differ",
    )
    return rule


def native_inputs(root, commit):
    return {
        blob.name: blob.identity
        for blob in inventory(root, commit, PRODUCT)
        if blob.name == "CMakeLists.txt"
        or blob.name.startswith(("src/", "include/", "apps/"))
    }


def lineage(root, model_root, engine, network, rule, source_commit):
    root, model_root = Path(root), Path(model_root)
    paths = {
        "original_model_campaign": model_root / "MODEL_CAMPAIGN.json",
        "original_selection": model_root / "selection/SELECTION.json",
        "selected_float_checkpoint": model_root / "selection/selected.pt",
        "original_protocol": root / "config/protocol-v3.json",
        "independent_learning": model_root / "INDEPENDENT_LEARNING.json",
        "wire_export": root / "results/precision-v4-2026-10-25/macos/EXPORT.json",
    }
    for name, expected in [
        ("original_model_campaign", MODEL_RECEIPT),
        ("original_selection", SELECTION),
        ("selected_float_checkpoint", CHECKPOINT),
        ("original_protocol", ORIGINAL_PROTOCOL),
        ("independent_learning", INDEPENDENT_LEARNING),
        ("wire_export", WIRE_EXPORT),
    ]:
        require(
            sha(paths[name]) == expected,
            "v4 real learning/selection bytes differ: " + name,
        )
    model, selection, learning, export = [
        document(paths[name])
        for name in [
            "original_model_campaign",
            "original_selection",
            "independent_learning",
            "wire_export",
        ]
    ]
    require(
        model["checkpoint_sha256"] == CHECKPOINT
        and model["protocol_sha256"] == ORIGINAL_PROTOCOL
        and model["seeds"] == [17, 41, 73]
        and model["updates_per_seed"] == 20000
        and model["test_model_metrics_used_for_selection"] is False
        and model["dataset_sha256"] == rule["data"]["dataset_sha256"],
        "v4 original learning receipt is inconsistent",
    )
    chosen = selection["selected"]
    require(
        selection["test_accessed"] is False
        and chosen["seed"] == 73
        and chosen["step"] == 2750
        and chosen["checkpoint_sha256"] == CHECKPOINT
        and [row["seed"] for row in selection["all_seeds"]] == [17, 41, 73]
        and all(row["completed_updates"] == 20000 for row in selection["all_seeds"]),
        "v4 validation-only selected checkpoint differs",
    )
    require(
        learning["status"] == "passed"
        and learning["profile"] == "full-learning-domain"
        and learning["selected_seed"] == 73
        and learning["seeds"] == [17, 41, 73]
        and learning["all_checkpoints_independently_evaluated"] == 240
        and learning["validation_positions_per_checkpoint"] == 8192
        and learning["test_arrays_opened"] is False
        and learning["network_sha256"] == model["network_sha256"],
        "v4 independent original learning proof differs",
    )
    require(
        export["status"] == "passed"
        and export["original_float_parameters_unchanged"] is True
        and export["same_real_activation_ceiling"] is True
        and export["legacy_export_byte_identical"] is True
        and export["checkpoint_sha256"] == CHECKPOINT
        and export["network"]["sha256"] == NETWORK,
        "v4 original wire derivation proof differs",
    )
    require(
        sha(engine) == ENGINE and sha(network) == NETWORK,
        "v4 supplied native/network bytes differ",
    )
    raw = Path(network).read_bytes()
    require(
        raw[:8] == b"CAISSAN4"
        and struct.unpack_from("<8I", raw, 8) == (4, 1, 12288, 64, 32, 16, 4096, 8188)
        and raw[40:104].decode("ascii") == CHECKPOINT
        and struct.unpack_from("<I", raw, 116)[0] == 1
        and zlib.crc32(raw[120:]) == struct.unpack_from("<I", raw, 112)[0],
        "v4 saved network arithmetic/lineage header differs",
    )
    require(
        native_inputs(root, source_commit) == native_inputs(root, COMPILED_SOURCE),
        "v4 native inputs differ from the tested saved image",
    )
    require(
        sha(root / "config/strength-openings.json") == OPENINGS,
        "v4 held-out opening bytes differ",
    )
    return {
        "schema": "caissa-derived-strength-actor-v1",
        "source_commit": source_commit,
        "engine_sha256": ENGINE,
        "network_sha256": NETWORK,
        "checkpoint_sha256": CHECKPOINT,
        "original_model_campaign_sha256": MODEL_RECEIPT,
        "original_model_failed_domains": model["failed_domains"],
        "original_receipt_unchanged": True,
        "selected_seed": 73,
        "selected_step": 2750,
        "paths": {
            name: {"path": str(path), "sha256": sha(path)}
            for name, path in paths.items()
        },
        "native_git_blobs": native_inputs(root, COMPILED_SOURCE),
        "full_acceptance": False,
    }


def configuration(rule, engine, network, openings, setting=None):
    config = original_configuration(rule, engine, network, openings, setting)
    config["candidate"]["options"]["Lazy Neural"] = True
    if setting is None:
        config["opponent"]["options"]["Lazy Neural"] = True
    full_actor_options(config["candidate"], config["opponent"], rule, setting is None)
    return config
