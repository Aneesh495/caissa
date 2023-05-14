"""Independent admission and replay of original search-system comparisons.

These results describe thread and heuristic effects. They never replace the
neural contribution endpoint, race instrumentation or the full G10 gate.
"""

import argparse
import hashlib
import json
import math
import re
import time
from pathlib import Path

from verification.bundle import digest_text, strict_json
from verification.draw_history import typed_equal
from verification.source import require

BASE = "a8623bf2d59561d434546ad612c939f994a4e699b1c61f4eba5b3114f26528dd"
SWITCHES = {
    "null": "Null Move",
    "lmr": "LMR",
    "extensions": "Extensions",
    "futility": "Futility",
    "see": "SEE",
    "history": "History",
    "pvs": "PVS",
    "aspiration": "Aspiration",
    "quiescence": "Quiescence",
    "table": "Use Table",
}


def read(path, maximum=4 * 1024**2):
    path = Path(path)
    require(
        path.is_file() and not path.is_symlink() and 0 < path.stat().st_size <= maximum,
        "systems comparison input is missing, linked or excessive",
    )
    raw = path.read_bytes()
    require(len(raw) <= maximum, "systems comparison input grew past its byte cap")
    return raw, strict_json(raw)


def schedule(kind):
    if kind == "parallel":
        return [
            {
                "id": f"threads-{threads}-ms-{budget}",
                "threads": threads,
                "switch": None,
                "budget_kind": "milliseconds",
                "budget": budget,
                "pairs": 100,
            }
            for threads in [2, 4, 8]
            for budget in [100, 400]
        ]
    require(kind == "heuristics", "unknown systems comparison domain")
    return [
        {
            "id": f"{switch}-{budget_kind}-{budget}",
            "threads": 1,
            "switch": name,
            "budget_kind": budget_kind,
            "budget": budget,
            "pairs": 50 if budget_kind == "milliseconds" else 25,
        }
        for switch, name in SWITCHES.items()
        for budget_kind, budgets in [
            ("milliseconds", [100, 400]),
            ("nodes", [20000, 100000]),
        ]
        for budget in budgets
    ]


def contract(profile, base):
    raw, rule = read(profile)
    base_raw, original = read(base)
    require(hashlib.sha256(base_raw).hexdigest() == BASE, "original v4 profile differs")
    require(
        set(rule)
        == {
            "schema",
            "status",
            "base_protocol_sha256",
            "kind",
            "comparisons",
            "resources",
        }
        and rule["schema"] == "caissa-systems-strength-protocol-v1"
        and rule["status"] == "frozen"
        and rule["base_protocol_sha256"] == BASE,
        "systems comparison profile schema or original actor lineage differs",
    )
    kind = rule["kind"]
    expected = schedule(kind)
    require(
        typed_equal(rule["comparisons"], expected),
        "systems comparison matrix is missing, reordered, weakened or duplicated",
    )
    seconds = 28800 if kind == "parallel" else 43200
    require(
        typed_equal(
            rule["resources"],
            {
                "maximum_wall_seconds": seconds,
                "maximum_active_seconds": seconds,
                "maximum_attempts": 3,
                "maximum_additional_bytes": 20 * 1024**3,
                "minimum_free_bytes": 10 * 1024**3,
                "workers": 1 if kind == "parallel" else 2,
                "parent_deadline_unix": 1793150297.974828,
                "output": f"runs/full-{kind}-strength-v1",
            },
        ),
        "systems comparison cumulative resource contract differs",
    )
    return rule, original, hashlib.sha256(raw).hexdigest()


def actor_options(kind, comparison, role):
    options = {
        "Threads": comparison["threads"] if role == "candidate" else 1,
        "Hash": 16,
        "Use Neural": kind == "parallel",
        "Evaluation Cache": True,
        "Tactical Generation": True,
        "Lazy Neural": True,
        "Neural Bounds": False,
        "Ordering Hints": False,
        **{name: True for name in SWITCHES.values()},
    }
    if kind == "parallel":
        options["Neural Weight"] = 10
    elif role == "opponent":
        options[comparison["switch"]] = False
    return options


def admission(identity, preflight, rule, original, comparison):
    config = identity["config"]
    budget_kind = comparison["budget_kind"]
    require(
        set(config)
        == {
            "profile",
            "candidate",
            "opponent",
            "openings",
            "pairs",
            budget_kind,
            "max_plies",
            "warmup_nodes",
            "transport_allowance_ms",
        }
        and config["profile"] == "full original " + rule["kind"] + " comparison",
        "systems raw campaign configuration inventory differs",
    )
    require(
        typed_equal(
            {
                key: config[key]
                for key in [
                    "pairs",
                    budget_kind,
                    "max_plies",
                    "warmup_nodes",
                    "transport_allowance_ms",
                ]
            },
            {
                "pairs": comparison["pairs"],
                budget_kind: comparison["budget"],
                "max_plies": 512,
                "warmup_nodes": 1,
                "transport_allowance_ms": 150,
            },
        ),
        "systems fixed sample, search budget or adjudication contract differs",
    )
    frozen = original["strength_actor"]
    require(
        identity["openings_sha256"] == frozen["openings_sha256"],
        "systems campaign changed the held-out opening identity",
    )
    commands, networks = [], []
    for role in ["candidate", "opponent"]:
        actor = identity["executables"][role]
        require(
            actor["executable"] == frozen["engine_sha256"]
            and typed_equal(actor["options"], config[role]["options"])
            and typed_equal(actor["command"], config[role]["command"])
            and isinstance(actor["command"], list)
            and len(actor["command"]) == 1
            and isinstance(actor["command"][0], str)
            and 0 < len(actor["command"][0]) <= 4096,
            "systems executable, options or command identity differs",
        )
        commands.append(actor["command"])
        require(
            not any(char in actor["command"][0] for char in "\r\n\0"),
            "systems executable path has a protocol delimiter",
        )
        options = actor["options"]
        expected = actor_options(rule["kind"], comparison, role)
        without_file = {
            key: value for key, value in options.items() if key != "EvalFile"
        }
        require(
            typed_equal(without_file, expected),
            "systems actors changed an unrelated search option or selected mixture",
        )
        if rule["kind"] == "parallel":
            require(
                actor.get("network_sha256") == frozen["network_sha256"]
                and isinstance(options.get("EvalFile"), str)
                and 0 < len(options["EvalFile"]) <= 4096
                and not any(char in options["EvalFile"] for char in "\r\n\0"),
                "systems neural actor changed the validation-selected network",
            )
            networks.append(options["EvalFile"])
        else:
            require(
                "EvalFile" not in options and "network_sha256" not in actor,
                "systems heuristic control must use the unchanged classical evaluator",
            )
        wire = preflight[role]
        declared = wire["declared_options"]
        sent = [
            f"setoption name {key} value {str(value).lower() if type(value) is bool else value}"
            for key, value in options.items()
        ]
        require(
            wire["executable_sha256"] == actor["executable"]
            and typed_equal(wire.get("configuration_commands"), sent),
            "systems actual configured UCI commands differ from frozen actors",
        )
        for key, value in options.items():
            spec = declared.get(key, {})
            if type(value) is bool:
                valid = spec.get("type") == "check"
            elif type(value) is int:
                valid = (
                    spec.get("type") == "spin"
                    and isinstance(spec.get("min"), str)
                    and isinstance(spec.get("max"), str)
                    and re.fullmatch(r"-?\d{1,12}", spec["min"]) is not None
                    and re.fullmatch(r"-?\d{1,12}", spec["max"]) is not None
                    and int(spec["min"]) <= value <= int(spec["max"])
                )
            else:
                valid = spec.get("type") == "string" and key == "EvalFile"
            require(
                valid,
                "systems requested option is absent or outside its UCI declaration",
            )
    require(
        commands[0] == commands[1] and (not networks or networks[0] == networks[1]),
        "systems paired actors must use the identical saved executable/network paths",
    )
    return config


def verify(
    campaign, profile, base, expected, comparison_id, openings, maximum_seconds=3600
):
    from tools.heuristic_study import avoid_decisive_matches
    from verification.match_journals import verify as journals
    from verification.strength import verify_campaign

    avoid_decisive_matches()
    require(
        type(maximum_seconds) in {int, float}
        and math.isfinite(maximum_seconds)
        and 0 < maximum_seconds <= 3600,
        "finite systems comparison replay ceiling required",
    )
    started, wall = time.monotonic(), time.time()

    def tick():
        require(
            time.monotonic() - started < maximum_seconds
            and time.time() - wall < maximum_seconds,
            "systems comparison original replay deadline exhausted",
        )

    rule, original, actual = contract(profile, base)
    require(
        digest_text(expected) == actual, "systems profile external identity differs"
    )
    matches = [row for row in rule["comparisons"] if row["id"] == comparison_id]
    require(len(matches) == 1, "unknown systems comparison identity")
    campaign = Path(campaign)
    metadata = [
        Path(profile),
        Path(base),
        campaign / "CONFIG.json",
        campaign / "PROTOCOL.json",
        campaign / "SUMMARY.json",
        Path(openings),
    ]
    pins = {path: hashlib.sha256(read(path)[0]).hexdigest() for path in metadata}
    _, identity = read(campaign / "CONFIG.json")
    _, preflight = read(campaign / "PROTOCOL.json")
    admission(identity, preflight, rule, original, matches[0])
    opening_bytes, _ = read(openings)
    require(
        hashlib.sha256(opening_bytes).hexdigest()
        == original["strength_actor"]["openings_sha256"],
        "systems reader must use the unchanged held-out openings",
    )
    tick()
    journal = journals(campaign, maximum_seconds=maximum_seconds, tick=tick)
    _, summary = read(campaign / "SUMMARY.json")
    require(
        summary.get("statistics_version") == 2
        and typed_equal(
            summary.get("bootstrap"),
            {
                "unit": "opening family containing color-reversed pairs",
                "resamples": 20000,
                "seed": 104729,
            },
        ),
        "systems comparison statistical procedure differs",
    )
    result = verify_campaign(
        campaign, openings, original["strength_actor"]["engine_sha256"], tick=tick
    )
    expected_games = matches[0]["pairs"] * 2
    require(
        result["statistics"]["games"] == expected_games
        and result["statistics"]["complete_pairs"] == matches[0]["pairs"],
        "systems comparison lacks its complete fixed sample",
    )
    for path, pinned in pins.items():
        tick()
        require(
            hashlib.sha256(read(path)[0]).hexdigest() == pinned,
            "systems comparison metadata changed during independent replay",
        )
    tick()
    return {
        **result,
        "comparison": comparison_id,
        "profile_sha256": actual,
        "kind": rule["kind"],
        "raw_journals": journal,
        "full_G10_certified": False,
        "neural_contribution_certified": False,
        "absolute_elo": None,
        "scope": "One complete systems-strength comparison; full matrix, performance and race instrumentation remain separate",
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("campaign", type=Path)
    parser.add_argument("--profile", type=Path, required=True)
    parser.add_argument("--expected-profile-sha256", required=True)
    parser.add_argument(
        "--base-protocol", type=Path, default=Path("config/protocol-v4.json")
    )
    parser.add_argument("--comparison", required=True)
    parser.add_argument(
        "--openings", type=Path, default=Path("config/strength-openings.json")
    )
    parser.add_argument("--maximum-seconds", type=float, default=3600)
    args = parser.parse_args()
    try:
        result = verify(
            args.campaign,
            args.profile,
            args.base_protocol,
            args.expected_profile_sha256,
            args.comparison,
            args.openings,
            args.maximum_seconds,
        )
    except (ValueError, KeyError, OSError, TypeError) as error:
        result = {"status": "rejected", "reason": str(error), "full_acceptance": False}
        print(json.dumps(result))
        raise SystemExit(1)
    print(json.dumps(result))


if __name__ == "__main__":
    main()
