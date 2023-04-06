"""Explicit wall-only continuation of the same immutable neural match sample.

The metadata watcher owns no arena. After the original wall failure and owner
exit, a separate lease charges original plus recovery compute and attempts.
"""

import argparse
import fcntl
import json
import math
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

from tools.campaign_process import Campaign, StageFailure, atomic
from tools.finalize_corpus import archive_source
from tools.full_strength import HostGuard
from tools.power_guard import POLICY, PowerGuard
from tools.recovery_scope import tree_bytes
from tools.strength_v4_profile import ENGINE, NETWORK, PARENT_DEADLINE, require, sha
from verification.source import PRODUCT, inventory

ORIGINAL = "runs/full-neural-strength-v4"
RECOVERY = "runs/full-neural-strength-v4-wall-recovery-v1"
WATCHER = "runs/full-neural-strength-v4-wall-watcher-v1"
AUTH = "work/strength-v4-wall-gap-2026-10-26/AUTHORIZATION.json"
AUTH_SHA = "f32ebbf3dca2c64cf79e606b4ac8c68a61f44885490600d32750551b58a72fc3"
PROPOSAL = "work/strength-v4-wall-gap-2026-10-26/PROPOSAL.json"
PROPOSAL_SHA = "3f4e4c5c3f48c751f564736a801d281c156d3399f8df288b1eff787b88c972f4"
OLD_SCOPE_SHA = "b80c2af13f5087d0872f8239a175e681e41fae53085a295bbb0f9449348a87fa"
PROFILE = "a8623bf2d59561d434546ad612c939f994a4e699b1c61f4eba5b3114f26528dd"
OLD_SOURCE = "9f3ac86ca38eb28b357ad7ef146f1af4bfb96021"
OLD_DEADLINE = 1792982806.744264


def read(path):
    require(path.is_file() and not path.is_symlink(), "missing or linked receipt")
    require(path.stat().st_size <= 16 * 1024 * 1024, "receipt byte ceiling")
    return json.loads(path.read_text())


def take_lock(path):
    stream = path.open("a")
    try:
        fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BaseException:
        stream.close()
        raise
    return stream


def authorized(root):
    require(sha(root / AUTH) == AUTH_SHA, "explicit human authorization changed")
    require(sha(root / PROPOSAL) == PROPOSAL_SHA, "approved proposal changed")
    auth, proposal = read(root / AUTH), read(root / PROPOSAL)
    require(
        auth["proposal_sha256"] == PROPOSAL_SHA
        and auth["human_answer"] == "Approve 5-hour wall recovery"
        and auth["maximum_additional_wall_seconds"] == 18000
        and auth["maximum_combined_neural_active_seconds"] == 43200
        and auth["maximum_combined_neural_attempts"] == 3
        and auth["parent_deadline_unix"] == PARENT_DEADLINE,
        "wall recovery is not the explicitly authorized scope",
    )
    old = root / ORIGINAL
    require(sha(old / "SCOPE.json") == OLD_SCOPE_SHA, "original scope changed")
    state = read(old / "SCOPE.json")
    require(
        state["deadline_unix"] == OLD_DEADLINE
        and state["bindings"] == proposal["actor_bindings"]
        and state["bindings"]["source_commit"] == OLD_SOURCE
        and state["maximum_active_seconds"] == 43200
        and state["maximum_additional_bytes"] == 20 * 1024**3
        and state["minimum_free_bytes"] == 10 * 1024**3,
        "original wall/actor/resource contract differs",
    )
    return state


def stopped_inputs(root, old_state):
    """Called only while both original and global timed-owner locks are held."""
    old = root / ORIGINAL
    failure = read(old / "FAILED.json")
    usage = read(old / "ACTIVE_USAGE.json")
    require(
        failure["original_deadline_unix"] == OLD_DEADLINE
        and failure["observed_unix"] >= OLD_DEADLINE - 1
        and ("timeout" in failure["reason"] or "deadline" in failure["reason"]),
        "original wall failure has not been preserved",
    )
    require(
        usage.get("closed") is True
        and usage.get("maximum_active_seconds") == 43200
        and type(usage.get("active_seconds")) in (int, float)
        and math.isfinite(usage["active_seconds"])
        and 0 <= usage["active_seconds"] < 43200,
        "original active ledger is unclosed, exhausted or invalid",
    )
    source_inputs = read(old / "SOURCE_INPUTS.json")
    for name, digest in [
        (
            "SOURCE_INPUTS.json",
            "14b3678bda1d0268bd8103d7a2e4bf4c62c4dcbeb41af117a2559fa6a2e7fb4f",
        ),
        (
            "DEPLOYMENT_LINEAGE.json",
            "f351af26cc7bbe124a5f13399158eae40881eeef0d35bcfce1639d65b8efb1cd",
        ),
        (
            "inputs/neural.json",
            "813962625e65d2f0eea351b10e80c651fad5727564f0b3ca1b0c86934262c24c",
        ),
        (
            "inputs/OPENINGS.json",
            "61b8c8812a107e0ea0b6e8a763a0d52d088b6b8480a0879a4952c4689bae71a8",
        ),
    ]:
        require(sha(old / name) == digest, "original saved input/lineage changed")
    require(source_inputs["commit"] == OLD_SOURCE, "original source identity differs")
    for name, digest in source_inputs["files"].items():
        require(sha(old / "source" / name) == digest, "original archived code changed")
    for name, digest in [
        ("bin/caissa", ENGINE),
        ("inputs/selected.cai", NETWORK),
        ("inputs/PROTOCOL.json", PROFILE),
    ]:
        require(sha(old / name) == digest, "saved original actor/profile changed")
    attempts = len(list((old / "attempts").glob("attempt-*")))
    require(1 <= attempts < 3, "combined attempt allowance exhausted")
    return {
        "original_scope_sha256": OLD_SCOPE_SHA,
        "original_failure_sha256": sha(old / "FAILED.json"),
        "original_usage_sha256": sha(old / "ACTIVE_USAGE.json"),
        "original_active_seconds": usage["active_seconds"],
        "original_attempts": attempts,
        "original_deadline_unix": old_state["deadline_unix"],
        "authorization_sha256": AUTH_SHA,
        "source_commit": OLD_SOURCE,
        "protocol_sha256": PROFILE,
        "engine_sha256": ENGINE,
        "network_sha256": NETWORK,
    }


class CombinedScope:
    """One contiguous extra wall window, with original usage charged forever."""

    def __init__(self, root, original, old_state, bindings, *, resume=False):
        self.root, self.original = Path(root), Path(original)
        self.root.mkdir(exist_ok=resume)
        self.lock = take_lock(self.root / "OWNER.lock")
        self.start = time.monotonic()
        self.active_used = 0.0
        self.last_write = self.last_size = -math.inf
        self.closed = False
        self.state = {
            "schema": "caissa-wall-only-combined-strength-scope-v1",
            "bindings": bindings,
            "origin_unix": old_state["deadline_unix"],
            "deadline_unix": min(old_state["deadline_unix"] + 18000, PARENT_DEADLINE),
            "maximum_additional_wall_seconds": 18000,
            "maximum_combined_active_seconds": 43200,
            "maximum_combined_attempts": 3,
            "maximum_additional_bytes": old_state["maximum_additional_bytes"],
            "minimum_free_bytes": old_state["minimum_free_bytes"],
            "data_root": old_state["data_root"],
            "initial_data_bytes": old_state["initial_data_bytes"],
        }
        try:
            require(
                bindings["original_active_seconds"] < 43200,
                "active allowance exhausted",
            )
            require(bindings["original_attempts"] < 3, "attempt allowance exhausted")
            require(
                time.time() >= self.state["origin_unix"],
                "original scope is still active",
            )
            if resume:
                require(
                    read(self.root / "SCOPE.json") == self.state,
                    "recovery scope changed",
                )
                used = read(self.root / "ACTIVE_USAGE.json")
                require(
                    used["maximum_combined_active_seconds"] == 43200
                    and used["original_active_seconds"]
                    == bindings["original_active_seconds"]
                    and type(used["closed"]) is bool
                    and type(used["recovery_active_seconds"]) in (int, float)
                    and math.isfinite(used["recovery_active_seconds"])
                    and used["recovery_active_seconds"] >= 0
                    and math.isfinite(used["monotonic_stamp"]),
                    "invalid recovery active ledger",
                )
                self.active_used = used["recovery_active_seconds"]
                if not used["closed"]:
                    elapsed = self.start - used["monotonic_stamp"]
                    require(
                        elapsed >= 0,
                        "unclosed recovery belongs to an earlier clock epoch",
                    )
                    self.active_used += elapsed
            else:
                atomic(self.root / "SCOPE.json", self.state)
            self.deadline = self.state["deadline_unix"]
            self.monotonic_deadline = self.start + max(0, self.deadline - time.time())
            self.check()
        except BaseException:
            self.lock.close()
            raise

    def remaining(self):
        return min(
            self.deadline - time.time(),
            self.monotonic_deadline - time.monotonic(),
            43200
            - self.state["bindings"]["original_active_seconds"]
            - self.active_used
            - (time.monotonic() - self.start),
        )

    def check(self):
        if self.remaining() <= 0:
            raise TimeoutError(
                "approved wall-only or combined active ceiling exhausted"
            )
        if shutil.disk_usage(self.root).free < self.state["minimum_free_bytes"]:
            raise ValueError("combined disk reserve exhausted")
        if time.monotonic() - self.last_write >= 1:
            self.record(False)
        if time.monotonic() - self.last_size >= 5:
            allocated = sum(
                tree_bytes(p)
                for p in [
                    self.root,
                    self.original,
                    self.state["data_root"],
                    self.original.parent / Path(WATCHER).name,
                ]
            )
            require(
                allocated - self.state["initial_data_bytes"]
                <= self.state["maximum_additional_bytes"],
                "combined additional disk ceiling exhausted",
            )
            self.last_size = time.monotonic()

    def record(self, closed):
        now = time.monotonic()
        recovery = self.active_used + now - self.start
        original = self.state["bindings"]["original_active_seconds"]
        atomic(
            self.root / "ACTIVE_USAGE.json",
            {
                "maximum_combined_active_seconds": 43200,
                "original_active_seconds": original,
                "recovery_active_seconds": recovery,
                "combined_active_seconds": original + recovery,
                "monotonic_stamp": now,
                "closed": closed,
            },
        )
        self.last_write = now

    def close(self):
        if not self.closed:
            self.record(True)
            self.closed = True
            self.lock.close()


def pin_journals(old, output, scope):
    path = output / "PRESERVED_JOURNALS.json"
    if path.exists():
        pins = read(path)
    else:
        files = {}
        for folder, suffixes in [("games", {".json", ".pgn"}), ("pairs", {".json"})]:
            for item in sorted((old / "neural" / folder).iterdir()):
                scope.check()
                require(not item.is_symlink(), "linked original journal")
                if item.suffix in suffixes:
                    files[str(item.relative_to(old))] = sha(item)
                elif item.suffix == ".tmp":
                    target = output / "retained-partials" / folder / item.name
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(item, target)
        require(len(files) <= 10000, "frozen 4000-game journal inventory exceeded")
        pins = {"schema": "caissa-original-journal-boundary-v1", "files": files}
        atomic(path, pins)
    verify_journals(old, pins, scope)
    return pins


def verify_journals(old, pins, scope):
    for name, digest in pins["files"].items():
        scope.check()
        require(sha(old / name) == digest, "completed original game/journal changed")


def recover(root, old_state, controller_inputs):
    old, output = root / ORIGINAL, root / RECOVERY
    original_lock = take_lock(old / "OWNER.lock")
    scope = campaign = power = None
    try:
        bindings = stopped_inputs(root, old_state)
        bindings["controller_source"] = controller_inputs
        scope = CombinedScope(output, old, old_state, bindings, resume=output.exists())
        attempts = sorted((output / "attempts").glob("attempt-*"))
        require(
            bindings["original_attempts"] + len(attempts) < 3,
            "combined attempt ceiling exhausted",
        )
        power = PowerGuard(POLICY)
        power.start(output)
        host = HostGuard(output, scope, power)
        host.check()
        campaign = Campaign(
            output / "attempts" / f"attempt-{len(attempts)+1:03d}",
            bindings,
            scope.remaining(),
            absolute_deadline=scope.deadline,
            resource_guard=host.check,
        )
        pins = pin_journals(old, output, scope)

        def run(name, module, args):
            host.check()
            return campaign.run(
                name,
                [sys.executable, "-m", module, *map(str, args)],
                scope.remaining(),
                cwd=old / "source",
            )

        run(
            "resume-missing-neural-games",
            "arena.run",
            [old / "inputs/neural.json", old / "neural", "--workers", 2],
        )
        verify_journals(old, pins, scope)
        run("statistics-neural", "arena.statistics", [old / "neural"])
        failed_gate = False
        try:
            run(
                "independent-neural",
                "verification.strength",
                [
                    old / "neural",
                    "--openings",
                    old / "inputs/OPENINGS.json",
                    "--engine-sha256",
                    ENGINE,
                    "--network-sha256",
                    NETWORK,
                    "--protocol",
                    old / "inputs/PROTOCOL.json",
                    "--neural",
                    "--require-full",
                ],
            )
        except StageFailure as error:
            observed = read(campaign.output / "independent-neural.log")
            if not (
                error.record["exit"] == 1
                and observed.get("reason")
                == "full neural contribution failed its predeclared Elo endpoint"
                and observed.get("observed", {}).get("games") == 4000
            ):
                raise
            failed_gate = True
        verify_journals(old, pins, scope)
        require(
            len(list((old / "neural/games").glob("*.json"))) == 4000,
            "incomplete frozen game sample",
        )
        receipt = {
            "schema": "caissa-approved-wall-recovery-result-v1",
            **bindings,
            "status": "completed fixed full neural sample",
            "failed_domains": (
                ["G08 neural contribution failed its frozen endpoint"]
                if failed_gate
                else []
            ),
            "original_scope_remains_failed": True,
            "scope_closed": True,
            "origin_unix": scope.state["origin_unix"],
            "deadline_unix": scope.deadline,
            "completed_unix": time.time(),
            "games": 4000,
            "independent_artifact": {
                "path": str(
                    (campaign.output / "independent-neural.log").relative_to(output)
                ),
                "sha256": sha(campaign.output / "independent-neural.log"),
            },
            "statistics_sha256": sha(old / "neural/SUMMARY.json"),
            "absolute_elo": None,
            "full_acceptance": False,
        }
        campaign.close("completed fixed sample; scientific endpoint preserved", receipt)
        scope.close()
        atomic(output / "STRENGTH_RECOVERY.json", receipt)
        return receipt
    except BaseException as error:
        if campaign is not None:
            campaign.close(
                "failed", {"type": type(error).__name__, "reason": str(error)}
            )
        if scope is not None:
            atomic(
                output
                / f"FAILED-{len(list((output / 'attempts').glob('attempt-*'))):03d}.json",
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
        original_lock.close()


def frozen_controller(root, watcher, expected_commit):
    path = watcher / "SOURCE_INPUTS.json"
    if path.exists():
        inputs = read(path)
        require(inputs["commit"] == expected_commit, "watcher source identity changed")
    else:
        require(
            subprocess.check_output(
                ["git", "rev-parse", "HEAD"], cwd=root, text=True, timeout=5
            ).strip()
            == expected_commit,
            "commit controller before watching",
        )
        require(
            not subprocess.check_output(
                ["git", "status", "--porcelain"], cwd=root, text=True, timeout=10
            ),
            "controller checkout must be committed",
        )
        inputs = {
            "commit": expected_commit,
            "files": {
                b.name: sha(root / b.name)
                for b in inventory(root, expected_commit, PRODUCT)
            },
        }
        archive_source(root, watcher / "source", expected_commit, inputs["files"])
        atomic(path, inputs)
    for name, digest in inputs["files"].items():
        require(
            sha(watcher / "source" / name) == digest,
            "archived recovery controller changed",
        )
    if Path(__file__).resolve() != watcher / "source/tools/strength_wall_recovery.py":
        launcher = "import runpy,sys;sys.path.insert(0,sys.argv.pop(1));runpy.run_module('tools.strength_wall_recovery',run_name='__main__')"
        os.execv(
            sys.executable,
            [
                sys.executable,
                "-P",
                "-c",
                launcher,
                str(watcher / "source"),
                *sys.argv[1:],
            ],
        )
    return {"commit": inputs["commit"], "manifest_sha256": sha(path)}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--expected-commit", required=True)
    args = parser.parse_args()
    root = Path.cwd().resolve()
    watcher = root / WATCHER
    watcher.mkdir(exist_ok=True)
    # Freeze before acquiring a descriptor that must survive the exec boundary.
    inputs = frozen_controller(root, watcher, args.expected_commit)
    owner = take_lock(watcher / "OWNER.lock")
    timed = None
    power = None
    try:
        state = authorized(root)
        power = PowerGuard(POLICY)
        power.start(watcher)
        deadline = min(OLD_DEADLINE + 18000, PARENT_DEADLINE)
        while time.time() < deadline:
            power.check()
            if (root / ORIGINAL / "STRENGTH_CAMPAIGN.json").exists():
                atomic(
                    watcher / "PROGRESS.json",
                    {
                        "status": "original owner completed; no recovery necessary",
                        "unix": time.time(),
                    },
                )
                return 0
            if time.time() >= OLD_DEADLINE:
                try:
                    timed = take_lock(root / "runs/TIMED_STRENGTH.lock")
                except BlockingIOError:
                    pass
                if timed is not None:
                    if (root / RECOVERY / "STRENGTH_RECOVERY.json").exists():
                        receipt = read(root / RECOVERY / "STRENGTH_RECOVERY.json")
                        require(
                            receipt["authorization_sha256"] == AUTH_SHA
                            and receipt["games"] == 4000,
                            "closed recovery identity differs",
                        )
                    else:
                        receipt = recover(root, authorized(root), inputs)
                    atomic(
                        watcher / "PROGRESS.json",
                        {
                            "status": "neural complete; handing off original external sample",
                            "unix": time.time(),
                        },
                    )
                    timed.close()
                    timed = None
                    # The original external owner enforces its own global lock,
                    # immutable source and separately frozen twelve-hour scope.
                    launcher = "import runpy,sys;sys.path.insert(0,sys.argv.pop(1));runpy.run_module('tools.strength_v4',run_name='__main__')"
                    power.close()
                    power = None
                    owner.close()
                    os.execv(
                        sys.executable,
                        [
                            sys.executable,
                            "-P",
                            "-c",
                            launcher,
                            str(root / ORIGINAL / "source"),
                            "external",
                            "--resume",
                            "--protocol",
                            str(root / ORIGINAL / "inputs/PROTOCOL.json"),
                            "--expected-protocol-sha256",
                            PROFILE,
                        ],
                    )
            atomic(
                watcher / "PROGRESS.json",
                {
                    "status": "metadata wait for unchanged original wall deadline/owner exit",
                    "unix": time.time(),
                    "original_deadline_unix": OLD_DEADLINE,
                    "approved_recovery_deadline_unix": deadline,
                },
            )
            time.sleep(min(5, max(0, deadline - time.time())))
        raise TimeoutError("approved contiguous recovery wall window exhausted")
    except BaseException as error:
        atomic(
            watcher / f"FAILED-{time.time_ns()}.json",
            {
                "type": type(error).__name__,
                "reason": str(error),
                "unix": time.time(),
                "full_acceptance": False,
            },
        )
        print(
            json.dumps(
                {"status": "failed", "reason": str(error), "full_acceptance": False}
            ),
            flush=True,
        )
        return 1
    finally:
        if timed is not None:
            timed.close()
        if power is not None:
            power.close()
        owner.close()


if __name__ == "__main__":
    raise SystemExit(main())
