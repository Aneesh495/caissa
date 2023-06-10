"""Stage immutable raw browser evidence for independent semantic reconstruction."""

import json
from pathlib import Path

from verification.browser import admit, verify as replay
from verification.source import require


def verify(bundle, inputs, output):
    domain = inputs["domains"]["G12"]
    arguments = domain["browser"]
    require(
        isinstance(arguments, dict) and set(arguments) == {"config"},
        "G12 requires the exact raw browser CONFIG reference",
    )
    name = bundle.reference(arguments["config"])
    prefix = str(Path(name).parent)
    require(
        prefix != "." and Path(name).name == "CONFIG.json",
        "G12 browser needs its own raw directory",
    )
    admit(
        bundle.json(name),
        inputs["engine"]["sha256"],
        inputs["network"]["artifact"]["sha256"],
        domain["source_commit"],
    )
    manifest_name = prefix + "/MANIFEST.json"
    manifest = bundle.json(manifest_name)
    require(
        isinstance(manifest, dict)
        and set(manifest) == {"files"}
        and isinstance(manifest["files"], dict),
        "G12 browser raw manifest is malformed",
    )
    expected = {prefix + "/" + path for path in manifest["files"]} | {manifest_name}
    present = {path for path in bundle.identities if path.startswith(prefix + "/")}
    declared = {bundle.reference(ref) for ref in domain["artifacts"]}
    require(
        present == expected and expected <= declared,
        "G12 browser raw inventory is missing, extra or undeclared",
    )
    output = Path(output).resolve()
    require(
        not output.is_relative_to(bundle.root), "G12 replay must preserve raw evidence"
    )
    output.mkdir(parents=True, exist_ok=False)
    raw = output / "raw"
    raw.mkdir()
    for path in sorted(expected):
        target = raw / path[len(prefix) + 1 :]
        target.parent.mkdir(parents=True, exist_ok=True)
        bundle.copy(path, target, 64 * 1024**2)
    result = replay(
        raw,
        inputs["engine"]["sha256"],
        inputs["network"]["artifact"]["sha256"],
        domain["source_commit"],
    )
    require(
        result["component_pass"] is True and result["full_G12_certified"] is False,
        "G12 component attempted to certify final-source product acceptance",
    )
    (output / "BROWSER_COMPONENT.json").write_text(json.dumps(result, indent=2) + "\n")
    return result
