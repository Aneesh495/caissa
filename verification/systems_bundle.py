"""Replay both frozen systems matrices from immutable full-bundle artifacts.

The matrix component cannot certify race instrumentation, latency or memory.
Recorded negative and unfinished games remain part of their original samples.
"""

import time
from pathlib import Path

from tools.campaign_process import atomic
from verification.draw_history import typed_equal
from verification.source import require
from verification.strength import StrengthFailure
from verification.strength_bundle import stage_campaign
from verification.systems_strength import BASE, contract

PROFILES = {
    "parallel": "5b405adcb7edbdc4bbae410612c7867879a83f73e635ed5ca29c26eeee072f48",
    "heuristics": "1d6bb4a26490d7ec4b4cc28c8da8fda0ad4dfd10678edcf2f2a69f13eba2f592",
}


def admit(bundle, inputs):
    domain = inputs["domains"]["G10"]
    arguments = domain["systems_strength"]
    require(
        isinstance(arguments, dict) and set(arguments) == {"matrices"},
        "G10 systems component requires its exact matrix inventory",
    )
    matrices = arguments["matrices"]
    require(
        isinstance(matrices, list)
        and len(matrices) == 2
        and all(isinstance(row, dict) for row in matrices)
        and [row.get("kind") for row in matrices] == list(PROFILES),
        "G10 systems component requires both frozen matrices in original order",
    )
    require(
        inputs["protocol"]["sha256"] == BASE,
        "G10 systems component requires the unchanged original v4 protocol",
    )
    declared = {bundle.reference(ref) for ref in domain["artifacts"]}
    profiles, configs = set(), set()
    for matrix in matrices:
        require(
            set(matrix) == {"kind", "profile", "campaigns"},
            "G10 matrix descriptor fields differ",
        )
        kind = matrix["kind"]
        profile = bundle.reference(matrix["profile"])
        require(
            matrix["profile"]["sha256"] == PROFILES[kind]
            and profile in declared
            and profile not in profiles,
            "G10 matrix profile is changed, duplicated or undeclared",
        )
        profiles.add(profile)
        # Validate complete typed schedules before staging or invoking a reader.
        from verification.systems_strength import schedule

        expected = schedule(kind)
        campaigns = matrix["campaigns"]
        require(
            isinstance(campaigns, list)
            and len(campaigns) == len(expected)
            and all(
                isinstance(row, dict) and set(row) == {"comparison", "config"}
                for row in campaigns
            )
            and typed_equal(
                [row["comparison"] for row in campaigns],
                [row["id"] for row in expected],
            ),
            "G10 matrix omitted, duplicated, reordered or replaced a comparison",
        )
        for campaign in campaigns:
            path = bundle.reference(campaign["config"])
            require(
                path in declared and path not in configs,
                "G10 comparison CONFIG is duplicated or undeclared",
            )
            configs.add(path)
    require(not profiles & configs, "G10 profiles cannot alias campaign CONFIGs")
    return matrices, declared


def verify(bundle, inputs, output):
    from tools.heuristic_study import avoid_decisive_matches
    from verification.systems_strength import verify as verify_comparison

    avoid_decisive_matches()
    matrices, declared = admit(bundle, inputs)
    output = Path(output).resolve()
    require(
        not output.is_relative_to(bundle.root),
        "G10 matrix replay must preserve the original evidence",
    )
    output.mkdir(parents=True, exist_ok=False)
    protocol = output / "BASE_PROTOCOL.json"
    protocol.write_bytes(bundle.bytes(bundle.reference(inputs["protocol"])))
    openings = output / "OPENINGS.json"
    opening_ref = inputs["heldout"]["config/strength-openings.json"]
    openings.write_bytes(bundle.bytes(bundle.reference(opening_ref)))
    observed = []
    try:
        for matrix in matrices:
            kind = matrix["kind"]
            directory = output / kind
            directory.mkdir()
            profile = directory / "PROFILE.json"
            profile.write_bytes(bundle.bytes(bundle.reference(matrix["profile"])))
            rule, original, pin = contract(profile, protocol)
            require(
                pin == PROFILES[kind]
                and original["strength_actor"]["engine_sha256"]
                == inputs["engine"]["sha256"]
                and original["strength_actor"]["network_sha256"]
                == inputs["network"]["artifact"]["sha256"],
                "G10 matrix saved actor differs from the full deployment",
            )
            for row, descriptor in zip(
                rule["comparisons"], matrix["campaigns"], strict=True
            ):
                bundle.tick()
                campaign = stage_campaign(
                    bundle,
                    {"config": descriptor["config"]},
                    declared,
                    directory / row["id"],
                    row["pairs"],
                )
                remaining = min(
                    bundle.monotonic_deadline - time.monotonic(),
                    bundle.wall_deadline - time.time(),
                )
                try:
                    result = verify_comparison(
                        campaign,
                        profile,
                        protocol,
                        pin,
                        row["id"],
                        openings,
                        maximum_seconds=min(3600, remaining),
                    )
                except StrengthFailure as error:
                    # Preserve complete but failed samples, then read the other
                    # fixed comparisons. No producer or replacement game runs.
                    result = {
                        "status": "failed",
                        "reason": str(error),
                        "observed": error.observed,
                    }
                bundle.tick()
                observed.append(
                    {"kind": kind, "comparison": row["id"], "result": result}
                )
                atomic(
                    output / "PROGRESS.json", {"comparisons_replayed": len(observed)}
                )
    except BaseException as error:
        atomic(output / "FAILED.json", {"reason": str(error), "completed": observed})
        raise
    result = {
        "status": (
            "passed"
            if all(row["result"]["status"] == "passed" for row in observed)
            else "failed"
        ),
        "comparisons": observed,
        "frozen_comparison_count": 46,
        "frozen_game_count": 4200,
        "full_gate": False,
        "full_acceptance": False,
        "pending_components": [
            "useful-work/memory/stop-latency join",
            "race instrumentation",
            "final source/runtime binding",
        ],
        "scope": "Both complete frozen systems-strength matrices only; no full G10 or neural gain certification",
    }
    atomic(output / "SYSTEMS_MATRICES.json", result)
    return result
