"""Resume only original parallel attempt3 under direct human environment steering.

No archived bytes, original scopes, game records or attempt ceilings are edited.
The explicit amendment permits battery and ordinary laptop work, records their
observations, and fixes the known archived verifier argument forwarding.
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
CONTENTION = "decisive timed games conflict with active compiler, data, training, arena or performance work"


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def authorization(approval, script_sha, scope_sha):
    if not (
        approval.get("approved") is True
        and approval.get("human_authorization_received") is True
        and approval.get("entrypoint_sha256") == script_sha
        and approval.get("original_scope_sha256") == scope_sha
        and approval.get("original_attempt") == 3
        and approval.get("extra_attempts_added") == 0
        and approval.get("extra_wall_seconds_added") == 0
        and approval.get("extra_active_seconds_added") == 0
        and approval.get("allow_battery") is True
        and approval.get("allow_normal_laptop_use") is True
    ):
        raise ValueError("specific human environment-resume authorization differs")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--check-only", action="store_true")
    args = parser.parse_args()
    root = Path.cwd().resolve()
    output = root / "runs/full-parallel-strength-v1"
    request = root / "work/systems-environment-resume-2026-10-26/AUTHORIZATION.json"
    approval = json.loads(request.read_bytes())
    authorization(approval, sha(__file__), sha(output / "SCOPE.json"))
    if "tools" in sys.modules or "verification" in sys.modules:
        raise ValueError("launch reviewed bootstrap by saved file path with python -P")
    sys.path.insert(0, str(output / "source"))
    from tools.campaign_process import atomic
    from tools.power_guard import BATTERY_POLICY
    from verification.draw_history import typed_equal
    from verification.source import PRODUCT, require, verify_archive
    import tools.systems_strength as owner

    source = json.loads((output / "SOURCE_INPUTS.json").read_bytes())
    scope = json.loads((output / "SCOPE.json").read_bytes())
    usage = json.loads((output / "ACTIVE_USAGE.json").read_bytes())
    require(source["commit"] == COMMIT, "original parallel source differs")
    verify_archive(root, output / "source", source, COMMIT, PRODUCT)
    require(
        Path(owner.__file__).resolve() == output / "source/tools/systems_strength.py",
        "parallel owner did not load from original archive",
    )
    require(
        sha(output / "inputs/PROFILE.json") == PROFILE,
        "original parallel profile differs",
    )
    require(
        usage["closed"] and usage["active_seconds"] < 28800,
        "original parallel owner is active or active budget exhausted",
    )
    require(
        time.time() < scope["deadline_unix"], "original parallel deadline exhausted"
    )
    require(
        len(list((output / "attempts").glob("attempt-*"))) == 2,
        "environment resume permits only original remaining attempt3",
    )
    require(
        not (output / "SYSTEMS_STRENGTH.json").exists(),
        "parallel domain already closed",
    )
    rule = json.loads((output / "inputs/PROFILE.json").read_bytes())
    for row in rule["comparisons"]:
        path = output / "inputs" / (row["id"] + ".json")
        config = json.loads(path.read_bytes())
        expected = owner.configuration(
            rule,
            row,
            output / "bin/caissa",
            output / "inputs/selected.cai",
            output / "inputs/OPENINGS.json",
        )
        require(
            typed_equal(config, expected), "saved actor/options or workload changed"
        )
        for role in ["candidate", "opponent"]:
            keys = list(config[role]["options"])
            require(
                keys.index("EvalFile") < keys.index("Use Neural"),
                "saved actor initialization ordering changed",
            )

    # The byte-identical historical caller reverses these two arguments.
    owner.verify_archive = lambda archive, checkout, *rest: verify_archive(
        checkout, archive, *rest
    )
    old_host = owner.HostGuard

    class ObserveNormalUse(old_host):
        def check(self):
            try:
                super().check()
            except ValueError as error:
                if str(error) != CONTENTION:
                    raise
                # The old observer has already recorded the actual process/load.
                # Resource, protocol, deadline, lease and disk failures still fail.

    owner.HostGuard = ObserveNormalUse
    owner.POLICY = dict(BATTERY_POLICY)
    original_args = SimpleNamespace(
        kind="parallel",
        profile=output / "inputs/PROFILE.json",
        expected_profile_sha256=PROFILE,
        expected_commit=COMMIT,
        resume=True,
        check_only=args.check_only,
    )
    if not args.check_only:
        amendment = output / "ENVIRONMENT_RESUME.json"
        require(
            not amendment.exists(),
            "environment resume already recorded; no duplicate start",
        )
        atomic(
            amendment,
            {
                "entrypoint_sha256": sha(__file__),
                "authorization_sha256": sha(request),
                "original_scope_sha256": sha(output / "SCOPE.json"),
                "original_attempt": 3,
                "allow_battery": True,
                "allow_normal_laptop_use": True,
                "original_source_and_actor_unchanged": True,
                "extra_attempts_added": 0,
                "extra_wall_seconds_added": 0,
                "extra_active_seconds_added": 0,
                "observed_unix": time.time(),
                "controlled_idle_measurement": False,
                "full_acceptance": False,
            },
        )
    print(json.dumps(owner.execute(root, original_args)))


if __name__ == "__main__":
    main()
