"""Review or execute one explicitly approved extra heuristic continuation start.

Original archives, profiles, scopes and past game records remain intact.
Only a new explicitly approved amendment can add one effective fourth start,
with the same original deadline, active limit, actor and remaining game schedule.
"""

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path
from types import SimpleNamespace

COMMIT = "67f89c1bd89b6a86bbeb70a03fb3286d8614de8f"
PROFILE = "1d6bb4a26490d7ec4b4cc28c8da8fda0ad4dfd10678edcf2f2a69f13eba2f592"
CONTENTION = "decisive timed games conflict with active compiler, data, training, arena or performance work"


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def authorization(approval, script_sha, scope_sha, proposal_sha, protected_sha):
    if not (
        approval.get("approved") is True
        and approval.get("human_authorization_received") is True
        and approval.get("entrypoint_sha256") == script_sha
        and approval.get("original_scope_sha256") == scope_sha
        and approval.get("proposal_sha256") == proposal_sha
        and approval.get("protected_records_sha256") == protected_sha
        and approval.get("original_attempt") == 4
        and approval.get("extra_attempts_added") == 1
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
    output = root / "runs/full-heuristics-strength-v1"
    request = (
        root / "work/heuristics-environment-continuation-2026-10-26/AUTHORIZATION.json"
    )
    approval = json.loads(request.read_bytes()) if request.exists() else None
    if approval is not None:
        authorization(
            approval,
            sha(__file__),
            sha(output / "SCOPE.json"),
            sha(request.parent / "PROPOSAL.json"),
            sha(request.parent / "PROTECTED_RECORDS.json"),
        )
    elif not args.check_only:
        raise ValueError(
            "one additional heuristic start requires direct human approval"
        )
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
    require(source["commit"] == COMMIT, "original heuristic source differs")
    verify_archive(root, output / "source", source, COMMIT, PRODUCT)
    require(
        Path(owner.__file__).resolve() == output / "source/tools/systems_strength.py",
        "heuristic owner did not load from original archive",
    )
    require(
        sha(output / "inputs/PROFILE.json") == PROFILE,
        "original heuristic profile differs",
    )
    require(
        usage["closed"] and usage["active_seconds"] < 43200,
        "original heuristic owner is active or active budget exhausted",
    )
    require(
        time.time() < scope["deadline_unix"], "original heuristic deadline exhausted"
    )
    require(
        len(list((output / "attempts").glob("attempt-*"))) == 3,
        "environment resume permits only one additional attempt4",
    )
    require(
        not (output / "SYSTEMS_STRENGTH.json").exists(),
        "heuristic domain already closed",
    )
    rule = json.loads((output / "inputs/PROFILE.json").read_bytes())
    for row in rule["comparisons"]:
        path = output / "inputs" / (row["id"] + ".json")
        if not path.exists():
            require(
                not (output / "matches" / row["id"]).exists(),
                "saved comparison is missing its original config",
            )
            continue
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
            if not config[role]["options"].get("Use Neural"):
                continue
            keys = list(config[role]["options"])
            require(
                keys.index("EvalFile") < keys.index("Use Neural"),
                "saved actor initialization ordering changed",
            )

    # This heuristic source already forwards archive arguments correctly.
    # Keep original profile bytes and its three consumed starts intact. The
    # effective fourth-start allowance exists only in this approved view.
    original_contract = owner.contract

    def authorized_contract(profile, base):
        rule, protocol, pin = original_contract(profile, base)
        require(
            rule["resources"]["maximum_attempts"] == 3,
            "original heuristic attempt cap differs",
        )
        rule = json.loads(json.dumps(rule))
        rule["resources"]["maximum_attempts"] = 4
        return rule, protocol, pin

    owner.contract = authorized_contract
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
        kind="heuristics",
        profile=output / "inputs/PROFILE.json",
        expected_profile_sha256=PROFILE,
        expected_commit=COMMIT,
        resume=True,
        check_only=args.check_only,
    )
    if not args.check_only:
        # Refuse before writing an amendment while another campaign owns the host.
        available = owner.HostLease(root / "runs")
        available.check()
        available.close()
        protected = json.loads((request.parent / "PROTECTED_RECORDS.json").read_bytes())
        for name, expected in protected.items():
            path = Path(name)
            require(
                not path.is_absolute() and ".." not in path.parts,
                "invalid protected original record path",
            )
            require(
                sha(output / path) == expected,
                "protected original input/game/failure changed: " + name,
            )
        amendment = output / "HEURISTIC_CONTINUATION.json"
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
                "original_attempt": 4,
                "allow_battery": True,
                "allow_normal_laptop_use": True,
                "original_source_and_actor_unchanged": True,
                "extra_attempts_added": 1,
                "extra_wall_seconds_added": 0,
                "extra_active_seconds_added": 0,
                "observed_unix": time.time(),
                "controlled_idle_measurement": False,
                "original_maximum_attempts": 3,
                "effective_maximum_attempts": 4,
                "full_acceptance": False,
            },
        )
    result = owner.execute(root, original_args)
    if args.check_only:
        result["requires_one_extra_start_approval"] = approval is None
        result["original_attempts_consumed"] = 3
        result["proposed_start_number"] = 4
    print(json.dumps(result))


if __name__ == "__main__":
    main()
