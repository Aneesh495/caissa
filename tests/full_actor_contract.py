"""Rehashed actor options cannot hide a weaker baseline or different search."""

import copy
import json
from pathlib import Path

from tools.full_strength import configuration
from verification.strength import full_actor_options


def main():
    rule = json.loads(Path("config/protocol-v3.proposed.json").read_text())
    rule["status"] = "frozen"
    config = configuration(
        rule,
        Path("/frozen/caissa"),
        Path("/frozen/model.cai"),
        Path("/frozen/openings.json"),
        None,
    )
    candidate, opponent = config["candidate"], config["opponent"]
    full_actor_options(candidate, opponent, rule, True)
    rejected = []
    for name, role, key, value in [
        ("weakened-classical-table", "opponent", "Use Table", False),
        ("both-table-disabled", "both", "Use Table", False),
        ("changed-mixture", "candidate", "Neural Weight", 25),
        ("scalar-only-candidate", "candidate", "Scalar Neural", True),
        ("missing-file", "candidate", "EvalFile", ""),
        ("changed-hash", "both", "Hash", 8),
    ]:
        left, right = copy.deepcopy(candidate), copy.deepcopy(opponent)
        if role in ("candidate", "both"):
            left["options"][key] = value
        if role in ("opponent", "both"):
            right["options"][key] = value
        try:
            full_actor_options(left, right, rule, True)
        except ValueError as error:
            rejected.append({"case": name, "reason": str(error)})
        else:
            raise AssertionError("changed full option inventory admitted: " + name)
    print(
        json.dumps({"status": "passed", "controls": rejected, "full_acceptance": False})
    )


if __name__ == "__main__":
    main()
