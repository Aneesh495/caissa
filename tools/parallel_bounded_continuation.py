"""Resume original parallel attempt4 under the new broad human repair authority.

Original archives/scopes and recorded games remain intact; separate runtime views record one new start and finite wall-only time.
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
        and approval.get("original_attempt") == 4
        and approval.get("extra_attempts_added") == 1
        and approval.get("maximum_new_wall_seconds") == 28800
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
    request = root / "work/parallel-bounded-continuation-2026-10-26/AUTHORIZATION.json"
    approval = json.loads(request.read_bytes())
    authorization(approval, sha(__file__), sha(output / "SCOPE.json"))
    if not (
        approval.get("proposal_sha256") == sha(request.parent / "PROPOSAL.json")
        and approval.get("protected_records_sha256")
        == sha(request.parent / "PROTECTED_RECORDS.json")
    ):
        raise ValueError(
            "parallel continuation proposal or protected input identity differs"
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
    require(time.time() < 1793150297.974828, "original parent deadline exhausted")
    require(
        len(list((output / "attempts").glob("attempt-*"))) == 3,
        "bounded parallel continuation permits only effective attempt4",
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
    original_contract = owner.contract

    def extended_contract(profile, base):
        rule, protocol, pin = original_contract(profile, base)
        require(
            rule["resources"]["maximum_attempts"] == 3,
            "original parallel start cap differs",
        )
        rule = json.loads(json.dumps(rule))
        rule["resources"]["maximum_attempts"] = 4
        return rule, protocol, pin

    owner.contract = extended_contract
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
    import importlib.util
    import tools.power_guard as archived_power
    import tools.full_strength as archived_host

    loaded = {}
    for filename, key in [
        ("telemetry_nonfatal.py", "telemetry_helper_sha256"),
        ("bounded_host_log.py", "bounded_host_helper_sha256"),
    ]:
        helper = root / "tools" / filename
        require(
            approval.get(key) == sha(helper),
            "parallel observer helper identity differs",
        )
        spec = importlib.util.spec_from_file_location(
            "caissa_parallel_" + helper.stem, helper
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        loaded[filename] = module
    bounded = loaded["bounded_host_log.py"]
    owner.HostGuard = bounded.archived_guard(owner.HostGuard)
    if not args.check_only:
        loaded["telemetry_nonfatal.py"].install(archived_power, archived_host, output)

    original_args = SimpleNamespace(
        kind="parallel",
        profile=output / "inputs/PROFILE.json",
        expected_profile_sha256=PROFILE,
        expected_commit=COMMIT,
        resume=True,
        check_only=args.check_only,
    )
    if not args.check_only:
        available = owner.HostLease(root / "runs")
        available.check()
        available.close()
        protected = json.loads((request.parent / "PROTECTED_RECORDS.json").read_bytes())
        for name, pin in protected.items():
            part = Path(name)
            require(
                not part.is_absolute() and ".." not in part.parts,
                "invalid protected parallel record path",
            )
            require(
                sha(output / part) == pin, "protected parallel record changed: " + name
            )
        wall_origin = time.time()
        wall_deadline = min(
            wall_origin + approval["maximum_new_wall_seconds"], 1793150297.974828
        )
        owner.RecoveryScope = bounded.wall_scope(
            owner.RecoveryScope, scope["deadline_unix"], wall_deadline
        )
        amendment = output / "PARALLEL_CONTINUATION_4.json"
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
                "wall_only_origin_unix": wall_origin,
                "maximum_new_wall_seconds": approval["maximum_new_wall_seconds"],
                "original_deadline_unix": scope["deadline_unix"],
                "approved_deadline_unix": wall_deadline,
                "original_active_limit_seconds": 28800,
                "original_maximum_attempts": 3,
                "effective_maximum_attempts": 4,
                "extra_active_seconds_added": 0,
                "observed_unix": time.time(),
                "controlled_idle_measurement": False,
                "full_acceptance": False,
            },
        )
    result = owner.execute(root, original_args)
    if args.check_only:
        result["actual_start_deferred_until_host_free"] = True
        result["maximum_new_wall_seconds"] = approval["maximum_new_wall_seconds"]
        result["original_active_limit_seconds"] = 28800
    print(json.dumps(result))


if __name__ == "__main__":
    main()
