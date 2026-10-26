"""Stage all original recovery archives for the explicit G11 join."""

import json
from pathlib import Path

from verification.recovery_join import verify as replay
from verification.source import require


def verify(bundle, inputs, checkout, source, output):
    domain = inputs["domains"]["G11"]
    arguments = domain["recovery_join"]
    require(
        isinstance(arguments, dict) and set(arguments) == {"config"},
        "G11 join requires one exact raw CONFIG reference",
    )
    name = bundle.reference(arguments["config"])
    prefix = str(Path(name).parent)
    require(
        prefix != "." and Path(name).name == "CONFIG.json",
        "G11 join raw input directory differs",
    )
    manifest_name = prefix + "/MANIFEST.json"
    manifest = bundle.json(manifest_name)
    require(
        isinstance(manifest, dict)
        and set(manifest) == {"files"}
        and isinstance(manifest["files"], dict),
        "G11 join raw manifest differs",
    )
    expected = {prefix + "/" + path for path in manifest["files"]} | {manifest_name}
    declared = {bundle.reference(ref) for ref in domain["artifacts"]}
    require(
        {path for path in bundle.identities if path.startswith(prefix + "/")}
        == expected
        and expected <= declared
        and len(expected) <= 32,
        "G11 join archive inventory missing, extra or undeclared",
    )
    config = bundle.json(name)
    require(
        config["engine_sha256"] == inputs["engine"]["sha256"]
        and config["network_sha256"] == inputs["network"]["artifact"]["sha256"],
        "G11 join does not use the full graph saved actor",
    )
    output = Path(output).resolve()
    require(
        not output.is_relative_to(bundle.root),
        "G11 join must preserve original full evidence",
    )
    raw = output / "raw"
    raw.mkdir(parents=True, exist_ok=False)
    for path in sorted(expected):
        target = raw / path[len(prefix) + 1 :]
        target.parent.mkdir(parents=True, exist_ok=True)
        bundle.copy(path, target, 256 * 1024**2)
    result = replay(
        raw, checkout, source, bundle.identities[manifest_name], output / "joined"
    )
    bundle.tick()
    (output / "G11.json").write_text(json.dumps(result, indent=2) + "\n")
    return result
