"""Replay complete strength domains from the immutable full evidence graph.

Staging reads every raw journal through Bundle's pinned file descriptors. No
saved receipt or summary can stand in for the independent semantic readers.
"""

import json
import time
from pathlib import Path

from verification.source import require


def stage_campaign(bundle, descriptor, declared, destination, expected_pairs):
    require(
        isinstance(descriptor, dict) and set(descriptor) == {"config"},
        "strength campaign descriptor must name its exact CONFIG reference",
    )
    config_path = bundle.reference(descriptor["config"])
    prefix = str(Path(config_path).parent)
    require(
        prefix != "." and Path(config_path).name == "CONFIG.json",
        "strength raw campaign needs its own bounded artifact directory",
    )
    identity = bundle.json(config_path)
    config = identity["config"]
    require(
        type(config.get("pairs")) is int
        and type(expected_pairs) is int
        and 1 <= expected_pairs <= 2000
        and config["pairs"] == expected_pairs,
        "strength raw campaign differs from its full fixed sample",
    )
    names = {"CONFIG.json", "PROTOCOL.json", "SUMMARY.json"}
    for number in range(expected_pairs):
        names.add(f"pairs/{number:06d}.json")
        for reverse in [0, 1]:
            names.update(
                f"games/{number:06d}-{reverse}.{extension}"
                for extension in ["json", "pgn"]
            )
    expected = {prefix + "/" + name for name in names}
    actual = {name for name in bundle.identities if name.startswith(prefix + "/")}
    require(
        actual == expected and expected <= declared,
        "strength raw campaign inventory is missing, extra or undeclared",
    )
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=False)
    for name in sorted(names):
        bundle.tick()
        limit = 4 * 1024 * 1024 if name.endswith(".pgn") else 64 * 1024 * 1024
        if name in {"CONFIG.json", "PROTOCOL.json", "SUMMARY.json"}:
            limit = 4 * 1024 * 1024
        raw = bundle.bytes(prefix + "/" + name, limit)
        target = destination / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)
    return destination


def verify(bundle, inputs, gate, output):
    from verification.external_strength import verify as external
    from verification.match_journals import verify as journals
    from verification.strength import verify_campaign

    require(gate in {"G08", "G09"}, "unsupported strength domain")
    domain = inputs["domains"][gate]
    arguments = domain["strength"]
    descriptors = arguments["campaigns"]
    require(
        isinstance(descriptors, list)
        and len(descriptors) == (1 if gate == "G08" else 3),
        "strength full domain has a missing or duplicated setting",
    )
    protocol = bundle.json(bundle.reference(inputs["protocol"]))
    rules = protocol["matches"]
    counts = [rules["neural_pairs"]] if gate == "G08" else rules["external_pairs"]
    require(
        counts == ([2000] if gate == "G08" else [334, 333, 333]),
        "strength adapter requires the complete frozen 4000/2000 game samples",
    )
    output = Path(output).resolve()
    require(
        not output.is_relative_to(bundle.root),
        "strength replay must preserve the original evidence",
    )
    output.mkdir(parents=True, exist_ok=False)
    declared = {bundle.reference(ref) for ref in domain["artifacts"]}
    opening_name = bundle.reference(inputs["heldout"]["config/strength-openings.json"])
    openings = output / "openings.json"
    openings.write_bytes(bundle.bytes(opening_name))
    staged, journal_results = [], []
    try:
        for index, (descriptor, count) in enumerate(zip(descriptors, counts)):
            destination = stage_campaign(
                bundle, descriptor, declared, output / f"campaign-{index}", count
            )
            remaining = min(
                bundle.monotonic_deadline - time.monotonic(),
                bundle.wall_deadline - time.time(),
            )
            journal_results.append(
                journals(
                    destination, maximum_seconds=min(3600, remaining), tick=bundle.tick
                )
            )
            staged.append(destination)
        engine = inputs["engine"]["sha256"]
        network = inputs["network"]["artifact"]["sha256"]
        if gate == "G08":
            result = verify_campaign(
                staged[0],
                openings,
                engine,
                network,
                protocol,
                neural=True,
                require_full=True,
                tick=bundle.tick,
            )
        else:
            result = external(
                staged, openings, engine, network, protocol, tick=bundle.tick
            )
        bundle.tick()
        result = {
            **result,
            "gate": gate,
            "raw_journal_replays": journal_results,
            "full_gate": True,
            "full_acceptance": False,
        }
    except (ValueError, KeyError, OSError, TypeError) as error:
        result = {
            "status": "rejected",
            "gate": gate,
            "reason": str(error),
            "raw_journal_replays": journal_results,
            "full_gate": False,
            "full_acceptance": False,
        }
        if hasattr(error, "observed"):
            result["observed"] = error.observed
        (output / "STRENGTH.json").write_text(json.dumps(result, indent=2) + "\n")
        raise
    (output / "STRENGTH.json").write_text(json.dumps(result, indent=2) + "\n")
    return result
