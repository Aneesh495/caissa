"""Reconstruct the arena recovery component from declared immutable artifacts.

An arena component can never certify training recovery, original data/splits
or the complete G11 gate, regardless of a saved status receipt.
"""

import json
from pathlib import Path

from verification.arena_recovery import FILES, admit, verify as replay
from verification.source import require


def verify_arena(bundle, inputs, output):
    domain = inputs["domains"]["G11"]
    reference = domain["arena_recovery"]
    require(
        isinstance(reference, dict) and set(reference) == {"config"},
        "G11 arena component must name its exact raw CONFIG reference",
    )
    name = bundle.reference(reference["config"])
    prefix = str(Path(name).parent)
    require(
        prefix != "." and Path(name).name == "CONFIG.json",
        "G11 arena raw component needs its own directory",
    )
    config = bundle.json(name)
    admit(config, inputs["engine"]["sha256"], domain["source_commit"])
    expected = {prefix + "/" + name for name in FILES}
    present = {name for name in bundle.identities if name.startswith(prefix + "/")}
    declared = {bundle.reference(ref) for ref in domain["artifacts"]}
    require(
        present == expected and expected <= declared,
        "G11 arena raw component inventory is missing, extra or undeclared",
    )
    output = Path(output).resolve()
    require(
        not output.is_relative_to(bundle.root),
        "G11 replay must preserve original raw evidence",
    )
    output.mkdir(parents=True, exist_ok=False)
    destination = output / "raw"
    destination.mkdir()
    for name in sorted(FILES):
        bundle.tick()
        target = destination / name
        target.parent.mkdir(parents=True, exist_ok=True)
        bundle.copy(
            prefix + "/" + name,
            target,
            64 * 1024**2 if name == "engine" else 4 * 1024**2,
        )
    result = replay(
        destination,
        inputs["engine"]["sha256"],
        domain["source_commit"],
        tick=bundle.tick,
        native_output=output / "native",
    )
    require(
        result["component_pass"] is True and result["full_G11_certified"] is False,
        "G11 arena component attempted to certify unrelated recovery domains",
    )
    result["training_and_data_recovery_still_required"] = True
    (output / "ARENA_RECOVERY.json").write_text(json.dumps(result, indent=2) + "\n")
    return result


def verify_training(bundle, inputs, output):
    from verification.training_recovery import admit, verify as replay_training

    domain = inputs["domains"]["G11"]
    arguments = domain["training_recovery"]
    require(
        isinstance(arguments, dict) and set(arguments) == {"config"},
        "G11 training component requires its exact raw CONFIG reference",
    )
    name = bundle.reference(arguments["config"])
    prefix = str(Path(name).parent)
    require(
        prefix != "." and Path(name).name == "CONFIG.json",
        "G11 training component needs its own raw directory",
    )
    admit(bundle.json(name), inputs["engine"]["sha256"], domain["source_commit"])
    manifest_name = prefix + "/MANIFEST.json"
    manifest = bundle.json(manifest_name)
    require(
        isinstance(manifest, dict)
        and set(manifest) == {"files"}
        and isinstance(manifest["files"], dict),
        "G11 training component raw manifest differs",
    )
    expected = {prefix + "/" + path for path in manifest["files"]} | {manifest_name}
    present = {path for path in bundle.identities if path.startswith(prefix + "/")}
    declared = {bundle.reference(ref) for ref in domain["artifacts"]}
    require(
        present == expected and expected <= declared,
        "G11 training raw inventory is missing, extra or undeclared",
    )
    output = Path(output).resolve()
    require(
        not output.is_relative_to(bundle.root),
        "G11 training reconstruction must preserve original evidence",
    )
    raw = output / "raw"
    raw.mkdir(parents=True, exist_ok=False)
    for name in sorted(expected):
        target = raw / name[len(prefix) + 1 :]
        target.parent.mkdir(parents=True, exist_ok=True)
        bundle.copy(name, target, 128 * 1024**2)
    result = replay_training(raw, inputs["engine"]["sha256"], domain["source_commit"])
    require(
        result["component_pass"] is True and result["full_G11_certified"] is False,
        "G11 training component attempted full project acceptance",
    )
    (output / "TRAINING_RECOVERY.json").write_text(json.dumps(result, indent=2) + "\n")
    return result
