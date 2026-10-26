"""A separately authorized admission shim for the original saved parallel owner.

The original source tree, scope, profile, actor and journals stay in place.
No new scope or attempt allowance is created by this entry point.
"""

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path
from types import SimpleNamespace

COMMIT = "d89b3e2139fef4dcbfdd6eac0dceaa1aec7c4829"
PROFILE = "5b405adcb7edbdc4bbae410612c7867879a83f73e635ed5ca29c26eeee072f48"


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--check-only", action="store_true")
    args = parser.parse_args()
    root = Path.cwd().resolve()
    output = root / "runs/full-parallel-strength-v1"
    if "tools" in sys.modules or "verification" in sys.modules:
        raise ValueError("launch this bootstrap by its saved file path with python -P")
    sys.path.insert(0, str(output / "source"))
    # Import every experiment dependency from the unchanged original archive.
    from tools.campaign_process import atomic
    from verification.draw_history import typed_equal
    from verification.source import PRODUCT, require, verify_archive
    import tools.systems_strength as owner

    source = json.loads((output / "SOURCE_INPUTS.json").read_bytes())
    scope = json.loads((output / "SCOPE.json").read_bytes())
    usage = json.loads((output / "ACTIVE_USAGE.json").read_bytes())
    require(source["commit"] == COMMIT, "different original parallel source")
    verify_archive(root, output / "source", source, COMMIT, PRODUCT)
    require(
        sha(output / "inputs/PROFILE.json") == PROFILE, "different parallel profile"
    )
    require(
        usage["closed"] and usage["active_seconds"] < 28800, "owner active or exhausted"
    )
    require(
        time.time() < scope["deadline_unix"], "original parallel deadline exhausted"
    )
    require(
        not (output / "SYSTEMS_STRENGTH.json").exists(),
        "parallel domain already closed",
    )
    attempts = list((output / "attempts").glob("attempt-*"))
    require(len(attempts) == 1, "this repair allows only the second original attempt")
    # This repair is only for the observed pre-game failure, never a new actor
    # or a rewrite of an existing game's protocol or configuration.
    require(
        not list((output / "matches").rglob("CONFIG.json")),
        "game configuration already committed",
    )
    require(
        not list((output / "matches").rglob("games/*.json")), "games already recorded"
    )
    require(
        Path(owner.__file__).resolve() == output / "source/tools/systems_strength.py",
        "owner did not load from original archive",
    )
    # The archived caller reversed these two parameters. Keep every saved
    # source byte and forward its call to the existing strict Git verifier.
    owner.verify_archive = lambda archive, checkout, *rest: verify_archive(
        checkout, archive, *rest
    )
    original_args = SimpleNamespace(
        kind="parallel",
        profile=output / "inputs/PROFILE.json",
        expected_profile_sha256=PROFILE,
        expected_commit=COMMIT,
        resume=True,
        check_only=args.check_only,
    )
    if args.check_only:
        print(json.dumps(owner.execute(root, original_args)))
        return
    authorization = root / "work/systems-startup-recovery-2026-10-26/AUTHORIZATION.json"
    approval = json.loads(authorization.read_bytes())
    require(
        approval.get("approved") is True
        and approval.get("entrypoint_sha256") == sha(__file__)
        and approval.get("original_scope_sha256") == sha(output / "SCOPE.json"),
        "specific startup repair approval missing or different",
    )
    rule = json.loads((output / "inputs/PROFILE.json").read_bytes())
    for row in rule["comparisons"]:
        config = owner.configuration(
            rule,
            row,
            output / "bin/caissa",
            output / "inputs/selected.cai",
            output / "inputs/OPENINGS.json",
        )
        path = output / "inputs" / (row["id"] + ".json")
        if path.exists():
            require(
                typed_equal(json.loads(path.read_bytes()), config),
                "saved actor values differ",
            )
            backup = attempts[0] / ("original-" + path.name)
            if backup.exists():
                require(
                    typed_equal(json.loads(backup.read_bytes()), config),
                    "original startup backup differs",
                )
            else:
                backup.write_bytes(path.read_bytes())
        for role in ["candidate", "opponent"]:
            options = config[role]["options"]
            config[role]["options"] = {
                **{k: v for k, v in options.items() if k != "Use Neural"},
                "Use Neural": options["Use Neural"],
            }
        expected = owner.configuration(
            rule,
            row,
            output / "bin/caissa",
            output / "inputs/selected.cai",
            output / "inputs/OPENINGS.json",
        )
        require(typed_equal(config, expected), "repair changed frozen actor values")
        atomic(path, config)
    print(json.dumps(owner.execute(root, original_args)))


if __name__ == "__main__":
    main()
