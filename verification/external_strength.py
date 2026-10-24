"""Independent full external-setting schedule, model identity and game replay."""

import argparse
import json
from pathlib import Path

from verification.protocol import read_json
from verification.strength import verify_campaign


def external_options(index, rules):
    common = {"Threads": rules["threads"], "Hash": rules["hash_mib"]}
    if index == 0:
        return {**common, "UCI_LimitStrength": False, "Skill Level": 0}
    if index == 1:
        return {**common, "UCI_LimitStrength": True, "UCI_Elo": 2000}
    if index == 2:
        return {**common, "UCI_LimitStrength": False, "Skill Level": 20}
    raise ValueError("unfrozen external opponent setting")


def verify(campaigns, openings, expected_engine, expected_network, protocol):
    rules = protocol["matches"]
    if (
        protocol["status"] != "frozen"
        or len(campaigns) != 3
        or rules["external_pairs"] != [334, 333, 333]
        or rules["external_settings"]
        != [
            "Stockfish 19 Skill Level 0",
            "Stockfish 19 UCI_Elo 2000",
            "Stockfish 19 unrestricted",
        ]
    ):
        raise ValueError("full external setting inventory or fixed sample changed")
    results = []
    for index, campaign in enumerate(campaigns):
        identity = read_json((campaign / "CONFIG.json").read_text())
        config = identity["config"]
        candidate, opponent = (
            identity["executables"]["candidate"],
            identity["executables"]["opponent"],
        )
        if (
            config["pairs"] != rules["external_pairs"][index]
            or opponent["executable"] != rules["stockfish_sha256"]
            or opponent["options"] != external_options(index, rules)
            or candidate.get("network_sha256") != expected_network
            or candidate["options"].get("Use Neural") is not True
            or candidate["options"].get("Neural Weight")
            != protocol["network"]["neural_weight"]
            or candidate["options"].get("Neural Bounds") is not False
            or candidate["options"].get("Ordering Hints") is not False
        ):
            raise ValueError("full external actor, model or setting differs")
        result = verify_campaign(
            campaign,
            openings,
            expected_engine,
            expected_network,
            protocol,
            neural=False,
            require_full=True,
        )
        if result["statistics"]["games"] != 2 * rules["external_pairs"][index]:
            raise ValueError("full external completed-game count is too small")
        results.append({"setting": rules["external_settings"][index], **result})
    return {
        "status": "passed",
        "scope": "full-external-strength",
        "games": sum(row["statistics"]["games"] for row in results),
        "settings": results,
        "absolute_elo": None,
        "absolute_rating_reason": "Stockfish option labels do not establish an absolute rating for Caissa",
        "full_acceptance": False,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("campaigns", nargs=3, type=Path)
    parser.add_argument("--openings", type=Path, required=True)
    parser.add_argument("--engine-sha256", required=True)
    parser.add_argument("--network-sha256", required=True)
    parser.add_argument("--protocol", type=Path, required=True)
    args = parser.parse_args()
    try:
        print(
            json.dumps(
                verify(
                    args.campaigns,
                    args.openings,
                    args.engine_sha256,
                    args.network_sha256,
                    read_json(args.protocol.read_text()),
                )
            )
        )
        return 0
    except (ValueError, KeyError, OSError) as error:
        result = {"status": "rejected", "reason": str(error), "full_acceptance": False}
        if hasattr(error, "observed"):
            result["observed"] = error.observed
        print(json.dumps(result))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
