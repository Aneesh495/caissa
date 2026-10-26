"""One bounded final-host profile and independent replay of the saved v4 actor."""

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

from tools.campaign_process import Campaign, atomic
from tools.finalize_corpus import archive_source
from tools.full_strength import HostGuard
from tools.host_lease import HostLease
from tools.power_guard import POLICY, PowerGuard
from tools.recovery_scope import RecoveryScope
from tools.strength_v4_profile import lineage
from verification.g07_audit import strength_settled
from verification.source import PRODUCT, require, snapshot, verify_checkout

PARENT_DEADLINE = 1793150297.974828
OUTPUT = "runs/full-performance-v4"


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def execute(commit):
    root = Path.cwd().resolve()
    output = root / OUTPUT
    require(strength_settled(root), "frozen strength sequence must settle first")
    require(not output.exists(), "final performance scope already exists; no reset")
    require(
        time.time() + 2400 <= PARENT_DEADLINE, "parent deadline cannot fit this scope"
    )
    require(
        not subprocess.check_output(
            ["git", "status", "--porcelain"], text=True, timeout=10
        ),
        "commit source before final performance",
    )
    source = {
        "schema": "caissa-source-inputs-v2",
        "policy": PRODUCT,
        "commit": commit,
        "files": snapshot(root, commit, PRODUCT),
    }
    verify_checkout(root, source, commit, PRODUCT)
    base = json.loads((root / "config/protocol-v4.json").read_bytes())
    actor = base["strength_actor"]
    frozen = root / "runs/full-neural-strength-v4"
    bindings = {
        "source_commit": commit,
        "engine_sha256": actor["engine_sha256"],
        "network_sha256": actor["network_sha256"],
        "profile_sha256": sha(root / "config/performance.json"),
        "parent_deadline_unix": PARENT_DEADLINE,
    }
    lease = HostLease(root / "runs")
    scope = power = campaign = None
    try:
        scope = RecoveryScope(
            output,
            bindings,
            2400,
            output / "empty-input-accounting",
            10,
            20,
            maximum_active_seconds=2400,
        )
        power = PowerGuard(POLICY if sys.platform == "darwin" else None)
        power.start(output)
        host = HostGuard(output, scope, power)

        def guard():
            lease.check()
            host.check()

        guard()
        atomic(output / "SOURCE_INPUTS.json", source)
        atomic(
            output / "PLAN.json",
            {
                **bindings,
                "maximum_seconds": 2400,
                "producer_seconds": 1800,
                "reader_seconds": 600,
                "maximum_attempts": 1,
                "maximum_additional_bytes": 20 * 1024**3,
                "minimum_free_bytes": 10 * 1024**3,
                "exact_optimizations": True,
                "lazy_neural": True,
                "full_acceptance": False,
            },
        )
        archive_source(root, output / "source", commit, source["files"])
        (output / "inputs").mkdir()
        (output / "bin").mkdir()
        for origin, target, expected in [
            (frozen / "bin/caissa", output / "bin/caissa", actor["engine_sha256"]),
            (
                frozen / "inputs/selected.cai",
                output / "inputs/selected.cai",
                actor["network_sha256"],
            ),
            (
                root / "config/performance.json",
                output / "inputs/PROFILE.json",
                bindings["profile_sha256"],
            ),
        ]:
            guard()
            require(sha(origin) == expected, "final performance input differs")
            shutil.copyfile(origin, target)
            require(sha(target) == expected, "final performance input copy differs")
        engine, network, profile = (
            output / "bin/caissa",
            output / "inputs/selected.cai",
            output / "inputs/PROFILE.json",
        )
        engine.chmod(0o755)
        atomic(
            output / "DEPLOYMENT_LINEAGE.json",
            lineage(
                root,
                root / "runs/searched-full-model-v3",
                engine,
                network,
                base,
                commit,
            ),
        )
        campaign = Campaign(
            output / "execution",
            bindings,
            scope.remaining(),
            absolute_deadline=scope.deadline,
            resource_guard=guard,
        )
        launcher = "import runpy,sys;sys.path.insert(0,sys.argv.pop(1));runpy.run_module(sys.argv.pop(1),run_name='__main__')"

        def run(name, module, arguments, seconds):
            return campaign.run(
                name,
                [
                    sys.executable,
                    "-B",
                    "-P",
                    "-c",
                    launcher,
                    str(output / "source"),
                    module,
                    *map(str, arguments),
                ],
                min(seconds, scope.remaining()),
                cwd=root,
                env=lease.environment(),
                pass_fds=(lease.stream.fileno(),),
                maximum_output_bytes=4 * 1024**2,
            )

        run(
            "producer",
            "tools.performance",
            [
                "--engine",
                engine,
                "--network",
                network,
                "--config",
                profile,
                "--output",
                output / "measurements",
                "--load-note",
                "Exclusive host lease held; process and power samples retained by the bounded owner. Residual system load remains visible.",
                "--exact-optimizations",
                "--lazy-neural",
                "--maximum-seconds",
                1800,
            ],
            1800,
        )
        run(
            "independent",
            "verification.performance",
            [
                output / "measurements",
                "--engine",
                engine,
                "--network",
                network,
                "--config",
                profile,
                "--expected-config-sha256",
                bindings["profile_sha256"],
                "--maximum-seconds",
                600,
                "--require-full",
                "--replay-output",
                output / "replay",
                "--inherit-process-group",
            ],
            600,
        )
        replay = json.loads((output / "execution/independent.log").read_bytes())
        require(
            replay["status"] == "passed"
            and replay["scope"] == "full performance workload replay",
            "full performance reader did not accept the complete sample",
        )
        result = {
            **bindings,
            "status": "passed performance sample",
            "independent_sha256": sha(output / "execution/independent.log"),
            "completed_unix": time.time(),
            "scope_closed": True,
            "final_source_binding_still_required": True,
            "strength_gain_inferred": False,
            "full_acceptance": False,
        }
        campaign.close("passed", result)
        atomic(output / "PERFORMANCE.json", result)
        return result
    except BaseException as error:
        if campaign is not None:
            campaign.close("failed", {"reason": str(error)})
        if output.exists():
            atomic(
                output / "FAILED.json",
                {
                    "reason": str(error),
                    "observed_unix": time.time(),
                    "full_acceptance": False,
                },
            )
        raise
    finally:
        if power is not None:
            power.close()
        if scope is not None:
            scope.close()
        lease.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--expected-commit", required=True)
    args = parser.parse_args()
    print(json.dumps(execute(args.expected_commit)))


if __name__ == "__main__":
    main()
