"""No unknown schema or changed lazy actor may bypass the full option parser.

These are contract controls, not a frozen experiment or observed strength run.
The unchanged v3 contract is exercised by tests.full_actor_contract.
"""

import copy
import json
from pathlib import Path

from tools.full_strength import configuration
from verification.strength import full_actor_options


def main():
    rule = json.loads(Path("config/protocol-v3.json").read_text())
    rule["schema"] = "caissa-experiment-protocol-v4"
    rule["network"].update({"format": 4, "scale": 4096, "clip": 8188})
    rule["search_optimizations"]["deferred_neural_state"] = True
    config = configuration(
        rule,
        Path("/frozen/caissa"),
        Path("/frozen/selected.cai"),
        Path("/frozen/openings.json"),
        None,
    )
    candidate, classical = config["candidate"], config["opponent"]
    for actor in [candidate, classical]:
        actor["options"]["Lazy Neural"] = True
    full_actor_options(candidate, classical, rule, True)
    full_actor_options(candidate, {"options": {}}, rule, False)
    controls = []
    cases = [
        "unknown-schema",
        "lazy-candidate",
        "lazy-classical",
        "lazy-both",
        "missing-lazy",
        "extra-option",
        "bool-thread",
        "integer-lazy",
        "changed-mixture",
        "old-wire",
        "changed-clip",
        "protocol-bool-thread",
        "control-network",
        "control-table",
    ]
    for case in cases:
        current, left, right = (
            copy.deepcopy(rule),
            copy.deepcopy(candidate),
            copy.deepcopy(classical),
        )
        if case == "unknown-schema":
            current["schema"] = "caissa-experiment-protocol-v400"
        elif case == "lazy-candidate":
            left["options"]["Lazy Neural"] = False
        elif case == "lazy-classical":
            right["options"]["Lazy Neural"] = False
        elif case == "lazy-both":
            for actor in [left, right]:
                actor["options"]["Lazy Neural"] = False
        elif case == "missing-lazy":
            del left["options"]["Lazy Neural"]
        elif case == "extra-option":
            left["options"]["Selective"] = False
        elif case == "bool-thread":
            left["options"]["Threads"] = True
        elif case == "integer-lazy":
            left["options"]["Lazy Neural"] = 1
        elif case == "changed-mixture":
            left["options"]["Neural Weight"] = 11
        elif case == "old-wire":
            current["network"]["format"] = 3
        elif case == "changed-clip":
            current["network"]["clip"] += 1
        elif case == "protocol-bool-thread":
            current["matches"]["threads"] = True
        elif case == "control-network":
            right["options"]["Use Neural"] = True
        elif case == "control-table":
            right["options"]["Use Table"] = False
        try:
            full_actor_options(left, right, current, True)
        except ValueError as error:
            controls.append({"case": case, "reason": str(error)})
        else:
            raise AssertionError("deferred full actor change admitted: " + case)
    print(
        json.dumps(
            {
                "status": "passed",
                "controls": controls,
                "full_acceptance": False,
                "scope": "Prospective parser controls only; no profile frozen or games run",
            }
        )
    )


if __name__ == "__main__":
    main()
