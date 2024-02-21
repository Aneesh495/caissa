"""One new human-authorized continuation of the immutable parallel sample."""

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import resource
import runpy
import shutil
import subprocess
import sys
import time
from types import SimpleNamespace

COMMIT = "d89b3e2139fef4dcbfdd6eac0dceaa1aec7c4829"
PROFILE = "5b405adcb7edbdc4bbae410612c7867879a83f73e635ed5ca29c26eeee072f48"
CONTENTION = "decisive timed games conflict with active compiler, data, training, arena or performance work"
MODULES = {"arena.run", "arena.statistics", "verification.systems_strength"}


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def validate(scope_path):
    scope = json.loads(scope_path.read_text())
    root = Path(scope["root"])
    if scope["status"] != "admitted" or time.time() >= scope["deadline_unix"]:
        raise ValueError("new finite continuation scope is not live")
    if scope["effective_attempt"] != 5 or scope["extra_active_seconds"] != 0:
        raise ValueError("new continuation attempt/active limit differs")
    for name, digest in scope["source_bindings"].items():
        if sha(root / name) != digest:
            raise ValueError("continuation source/input binding differs: " + name)
    quota = load(root / "tools/parallel_storage_quota.py", "caissa_storage_quota")
    budget = load(root / "tools/storage_budget.py", "caissa_storage_budget")
    return scope, root, quota, budget


def storage_check(scope, root, quota_module, budget, state=None):
    actual = budget.footprint([root, *map(Path, scope["external_paths"])])
    disk = shutil.disk_usage(root)
    data = scope["data_bytes"] - (state["data_used"] if state else 0)
    control = scope["control_bytes"] - (state["control_used"] if state else 0)
    quota_module.check_admission(actual["charged_bytes"], disk.used, data, control, scope["reserve_bytes"])
    if disk.free < 10 * 1024**3:
        raise ValueError("original free disk reserve exhausted")
    return {**actual, "mac_filesystem_used_bytes": disk.used, "observed_unix": time.time()}


def specification(scope, scope_path):
    return {**scope, "scope_sha256": sha(scope_path)}


def stage(scope_path, module, arguments):
    if module not in MODULES:
        raise ValueError("unknown continuation stage")
    scope, root, quota_module, budget = validate(scope_path)
    output = Path(scope["output"])
    os.chdir(output / "source")
    sys.path.insert(0, str(output / "source"))
    from tools.host_lease import inherited
    if not inherited(root / "runs/TIMED_STRENGTH.lock"):
        raise ValueError("child stage requires the real inherited exclusive host lease")
    quota = quota_module.Quota(specification(scope, scope_path))
    quota.install()
    sys.argv = [module, *arguments]
    runpy.run_module(module, run_name="__main__")


def execute(scope_path):
    scope, root, quota_module, budget = validate(scope_path)
    output = Path(scope["output"])
    if "tools" in sys.modules or "verification" in sys.modules:
        raise ValueError("launch by saved file path with python -B -P")
    sys.path.insert(0, str(output / "source"))
    from tools.campaign_process import atomic
    from tools.power_guard import BATTERY_POLICY
    from verification.source import PRODUCT, require, verify_archive
    from verification.draw_history import typed_equal
    import tools.systems_strength as owner
    import tools.power_guard as power_module
    import tools.full_strength as host_module

    usage = json.loads((output / "ACTIVE_USAGE.json").read_text())
    require(usage["closed"] and usage["active_seconds"] == scope["prior_active_seconds"], "original active ledger differs")
    require(len(list((output / "attempts").glob("attempt-*"))) == 4, "one fifth start only")
    require(not (output / "SYSTEMS_STRENGTH.json").exists(), "original domain already settled")
    source = json.loads((output / "SOURCE_INPUTS.json").read_text())
    require(source["commit"] == COMMIT and sha(output / "inputs/PROFILE.json") == PROFILE, "original actor/source/profile differs")
    verify_archive(root, output / "source", source, COMMIT, PRODUCT)
    for name, digest in scope["protected_prefix"].items():
        require(sha(output / name) == digest, "saved prefix differs: " + name)
    owner.verify_archive = lambda archive, checkout, *rest: verify_archive(checkout, archive, *rest)
    original_contract = owner.contract

    def contract(*args):
        rule, protocol, pin = original_contract(*args)
        require(rule["resources"]["maximum_attempts"] == 3 and rule["resources"]["maximum_active_seconds"] == 28800, "old limits differ")
        rule = json.loads(json.dumps(rule))
        rule["resources"]["maximum_attempts"] = 5
        return rule, protocol, pin
    owner.contract = contract
    rule = json.loads((output / "inputs/PROFILE.json").read_text())
    for row in rule["comparisons"]:
        path = output / "inputs" / (row["id"] + ".json")
        actual = json.loads(path.read_text())
        expected = owner.configuration(rule, row, output / "bin/caissa", output / "inputs/selected.cai", output / "inputs/OPENINGS.json")
        require(typed_equal(actual, expected), "saved schedule/actor options differ")
        for role in ("candidate", "opponent"):
            keys = list(actual[role]["options"])
            require(keys.index("EvalFile") < keys.index("Use Neural"), "saved initialization ordering differs")

    lease = owner.HostLease(root / "runs")
    quota = quota_module.Quota(specification(scope, scope_path))
    try:
        lease.check()
        actual_storage = storage_check(scope, root, quota_module, budget)
        quota.create()
        atomic(output / "PARALLEL_CONTINUATION_5.json", {
            "scope_sha256": sha(scope_path), "human_authorization_sha256": scope["human_authorization_sha256"],
            "started_unix": time.time(), "deadline_unix": scope["deadline_unix"],
            "original_parent_deadline_unix": 1793150297.974828,
            "new_parent_deadline_unix": scope["new_parent_deadline_unix"],
            "original_active_limit_seconds": 28800, "extra_active_seconds": 0,
            "original_prefix_games": 262, "original_prefix_pairs": 131,
            "storage_admission": actual_storage, "full_acceptance": False})
        owner.HostLease = lambda ignored: lease
        quota.install()
        old_scope = owner.RecoveryScope
        original_deadline = json.loads((output / "SCOPE.json").read_text())["deadline_unix"]

        class NewWall(old_scope):
            @property
            def deadline(self):
                return scope["deadline_unix"]

            @deadline.setter
            def deadline(self, value):
                require(value == original_deadline, "original scope deadline changed")
        owner.RecoveryScope = NewWall
        telemetry = load(root / "tools/telemetry_nonfatal.py", "caissa_telemetry")
        bounded = load(root / "tools/bounded_host_log.py", "caissa_bounded_host")
        telemetry.install(power_module, host_module, output)
        previous_host = bounded.archived_guard(owner.HostGuard)

        class StorageHost(previous_host):
            storage_last = -1e9

            def check(self):
                try:
                    super().check()
                except ValueError as error:
                    if str(error) != CONTENTION:
                        raise
                if shutil.disk_usage(root).used + scope["reserve_bytes"] > 400_000_000_000:
                    raise ValueError("actual Mac storage ceiling exhausted")
                if time.monotonic() - self.storage_last >= 30:
                    storage_check(scope, root, quota_module, budget, quota.read())
                    self.storage_last = time.monotonic()
        owner.HostGuard = StorageHost
        owner.POLICY = dict(BATTERY_POLICY)
        campaign_class = owner.Campaign

        class Campaign(campaign_class):
            def run(self, name, command, timeout, **kwargs):
                reused = scope["reused_stages"].get(name)
                if reused:
                    origin = output / reused["log"]
                    require(sha(origin) == reused["sha256"], "closed-stage receipt changed")
                    (self.output / (name + ".log")).write_bytes(origin.read_bytes())
                    record = {"event": "stage-reused-without-execution", "stage": name,
                              "exit": 0, "reason": "original completed stage retained",
                              "original_log": reused["log"], "sha256": reused["sha256"]}
                    atomic(self.output / (name + ".json"), record)
                    self._event(record)
                    return record
                require(command[:2] == [sys.executable, "-m"] and command[2] in MODULES, "unknown Python stage")
                command = [sys.executable, "-B", "-P", str(Path(__file__).resolve()),
                           "--scope", str(scope_path), "--stage", command[2], "--", *command[3:]]
                return super().run(name, command, timeout, **kwargs)
        owner.Campaign = Campaign
        args = SimpleNamespace(kind="parallel", profile=output / "inputs/PROFILE.json",
                               expected_profile_sha256=PROFILE, expected_commit=COMMIT,
                               resume=True, check_only=False)
        return owner.execute(root, args)
    finally:
        quota.uninstall()
        if quota.ledger.exists():
            quota.update(lambda state: state.update(closed=True, ended_unix=time.time()))
        lease.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--scope", type=Path, required=True)
    parser.add_argument("--stage", choices=sorted(MODULES))
    parser.add_argument("arguments", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    os.umask(0o077)
    sys.dont_write_bytecode = True
    os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
    resource.setrlimit(resource.RLIMIT_FSIZE, (40 * 1024**2, 40 * 1024**2))
    scope_path = args.scope.resolve()
    if args.stage:
        arguments = args.arguments[1:] if args.arguments[:1] == ["--"] else args.arguments
        stage(scope_path, args.stage, arguments)
    else:
        print(json.dumps(execute(scope_path)))


if __name__ == "__main__":
    main()
