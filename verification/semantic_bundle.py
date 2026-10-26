"""Stage exact G14 witnesses and run their independent mutation audit."""

import json
from pathlib import Path

from verification.semantic_audit import audit
from verification.source import require


def verify(bundle, inputs, checkout, source, output):
    domain = inputs["domains"]["G14"]
    arguments = domain["semantic_audit"]
    require(
        isinstance(arguments, dict) and set(arguments) == {"config"},
        "G14 requires its exact raw CONFIG reference",
    )
    name = bundle.reference(arguments["config"])
    prefix = str(Path(name).parent)
    require(
        prefix != "." and Path(name).name == "CONFIG.json",
        "G14 raw witness requires its own directory",
    )
    manifest_name = prefix + "/MANIFEST.json"
    manifest = bundle.json(manifest_name)
    require(
        isinstance(manifest, dict)
        and set(manifest) == {"files"}
        and isinstance(manifest["files"], dict),
        "G14 raw manifest is malformed",
    )
    expected = {prefix + "/" + path for path in manifest["files"]} | {manifest_name}
    declared = {bundle.reference(ref) for ref in domain["artifacts"]}
    require(
        {path for path in bundle.identities if path.startswith(prefix + "/")}
        == expected
        and expected <= declared
        and len(expected) <= 65,
        "G14 raw inventory is missing, extra or undeclared",
    )
    output = Path(output).resolve()
    require(
        not output.is_relative_to(bundle.root),
        "G14 replay must preserve original artifacts",
    )
    raw = output / "raw"
    raw.mkdir(parents=True, exist_ok=False)
    for path in sorted(expected):
        target = raw / path[len(prefix) + 1 :]
        target.parent.mkdir(parents=True, exist_ok=True)
        bundle.copy(path, target, 4 * 1024**2)
    result = audit(
        raw,
        checkout,
        source,
        inputs["engine"]["sha256"],
        inputs["network"]["artifact"]["sha256"],
        bundle.identities[manifest_name],
        output / "audit",
    )
    bundle.tick()
    (output / "G14.json").write_text(json.dumps(result, indent=2) + "\n")
    return result
