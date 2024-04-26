"""Finite owner for the missing exact-neural thread runtime component."""

import argparse
import json
import os
from pathlib import Path
import resource
import shutil
import signal
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.final_draw_runtime import digest, load_scope, specification
from tools.final_rules_runtime import RulesFile
from tools.parallel_storage_quota import Quota, StorageLimit, check_admission


class ThreadQuota(Quota):
    def classify(self, path, *, replacement=False):
        path = Path(path).absolute()
        if path != path.resolve() or not path.is_relative_to(self.output):
            raise StorageLimit("thread evidence escaped its scope")
        name = str(path.relative_to(self.output))
        if name == "producer/transcript.jsonl":
            if path.exists():
                raise StorageLimit("thread transcript is immutable")
            return "data", name
        canonical = name[:-4] if name.endswith(".tmp") else name
        names = {"WRITER.lock", "CONFIG.json", "COMMANDS.jsonl", "PROGRESS.json", "CAMPAIGN.json", "ACTIVE_USAGE.json", "FINAL_THREAD.json", "THREAD_RUNTIME.json", "FAILED-thread.json", "produce.log", "produce.json", "independent.log", "independent.json", "producer/PROGRESS.json", "producer/SUMMARY.json"}
        if self.spec.get("fixture_mode"):
            names.update({"fixture.txt", "producer/SYNTHETIC.json"})
        if canonical not in names:
            raise StorageLimit("unknown thread evidence destination")
        return "control", name

    def opener(self, original):
        opening = super().opener(original)
        def open_file(*args, **kwargs):
            stream = opening(*args, **kwargs)
            if hasattr(stream, "quota") and stream.quota is self:
                return RulesFile(self, stream.stream, stream.kind, stream.key, stream.credit, stream.binary)
            return stream
        return open_file


def bootstrap(path, stage):
    os.umask(0o077)
    scope = load_scope(path)
    from tools.host_lease import inherited
    if not inherited(ROOT / "runs/TIMED_STRENGTH.lock"):
        raise ValueError("thread stage lacks inherited actual host lease")
    quota = ThreadQuota(specification(scope, path))
    resource.setrlimit(resource.RLIMIT_FSIZE, (32 * 1024**2, 32 * 1024**2))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    quota.install()
    original = subprocess.Popen

    def popen(command, *args, **kwargs):
        if stage != "produce" or scope.get("fixture_mode") or command not in [[scope["release_engine"]], [scope["instrumented_engine"]]]:
            raise ValueError("unadmitted thread native command")
        image = Path(command[0])
        kind = "release" if str(image) == scope["release_engine"] else "instrumented"
        expected = scope["engine_sha256"] if kind == "release" else scope["instrumented_engine_sha256"]
        if digest(image) != expected or digest(scope["network"]) != scope["network_sha256"] or digest(scope["instrumented_runtime"]) != scope["instrumented_runtime_sha256"]:
            raise ValueError("thread native/model/runtime identity changed")
        if kwargs.get("stdout") != subprocess.PIPE or kwargs.get("stderr") != subprocess.PIPE:
            raise ValueError("thread actors require owned pipes")
        def count(state):
            state["native_starts"] = state.get("native_starts", 0) + 1
            key = kind + "_starts"
            state[key] = state.get(key, 0) + 1
            if state["native_starts"] > 8 or state[key] > 4:
                raise StorageLimit("fixed thread native-start inventory exhausted")
        quota.update(count)
        def limit():
            resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
            resource.setrlimit(resource.RLIMIT_FSIZE, (65536, 65536))
        kwargs.update(start_new_session=False, preexec_fn=limit)
        process = original(command, *args, **kwargs)
        if os.getpgid(process.pid) != os.getpgrp():
            process.kill()
            process.wait(timeout=2)
            raise ValueError("thread actor escaped its owning stage group")
        return process

    subprocess.Popen = popen
    def interrupt(*_):
        raise InterruptedError("thread stage termination requested")
    signal.signal(signal.SIGTERM, interrupt)
    if stage == "produce" and not scope.get("fixture_mode"):
        from tools.thread_probe import produce
        produce(scope, quota)
    elif stage == "independent" and not scope.get("fixture_mode"):
        from verification.thread_runtime import verify
        verify(scope)
    elif stage == "fixture" and scope.get("fixture_mode"):
        (Path(scope["output"]) / "fixture.txt").write_text("inherited thread quota/lease\n")
    else:
        raise ValueError("unadmitted thread stage")


def execute(path):
    os.umask(0o077)
    scope = load_scope(path)
    if scope.get("fixture_mode"):
        raise ValueError("fixture does not admit the thread owner")
    from tools.campaign_process import Campaign, atomic
    from tools.host_lease import HostLease
    from tools.storage_budget import footprint
    profile = json.loads(Path(scope["profile"]).read_text())
    if profile["status"] != "frozen" or digest(scope["profile"]) != scope["profile_sha256"]:
        raise ValueError("exact thread profile is not frozen and pinned")
    lease = HostLease(ROOT / "runs")
    quota = ThreadQuota(specification(scope, path))
    quota.create()
    resource.setrlimit(resource.RLIMIT_FSIZE, (65536, 32 * 1024**2))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    quota.install()
    campaign = None
    output = Path(scope["output"])
    last_storage = 0

    def guard(force=False):
        nonlocal last_storage
        lease.check()
        state = quota.read()
        if state.get("failure"):
            raise StorageLimit("thread storage failure latched")
        if force or time.monotonic() - last_storage >= 30:
            actual = footprint([ROOT, *scope["external_paths"]])
            check_admission(actual["charged_bytes"], shutil.disk_usage(ROOT).used, 0, scope["control_bytes"] - state["control_used"], scope["reserve_bytes"])
            last_storage = time.monotonic()
    try:
        guard(True)
        campaign = Campaign(output, {"schema": "caissa-new-exact-thread-runtime-v1", "scope_sha256": digest(path), "profile_sha256": scope["profile_sha256"], "match_games": 0}, scope["maximum_active_seconds"], absolute_deadline=scope["deadline_unix"], maximum_wall_seconds=scope["maximum_wall_seconds"], resource_guard=guard)
        atomic(output / "ACTIVE_USAGE.json", {"closed": False, "active_seconds": 0, "maximum_active_seconds": scope["maximum_active_seconds"]})
        common = [str(Path(sys.executable)), "-B", "-P", str(Path(__file__).resolve()), "--scope", str(path), "--stage"]
        for stage, allowance in [("produce", 480), ("independent", 90)]:
            campaign.run(stage, [*common, stage], allowance, maximum_output_bytes=32768, cwd=ROOT, env=lease.environment(), pass_fds=(lease.stream.fileno(),))
        result = json.loads((output / "THREAD_RUNTIME.json").read_text())
        state = quota.read()
        if result["status"] != "passed_exact_neural_thread_runtime_component" or state.get("native_starts") != 8 or state.get("release_starts") != 4 or state.get("instrumented_starts") != 4:
            raise ValueError("thread runtime/result/start endpoint incomplete")
        atomic(output / "FINAL_THREAD.json", {"status": "passed_exact_neural_thread_runtime_component", "reader_sha256": digest(output / "THREAD_RUNTIME.json"), "native_starts": 8, "match_games": 0, "full_G10_certified": False, "original_compiler_runtime_closure_established": False, "full_acceptance": False})
        campaign.close("passed-component")
    except BaseException as error:
        if output.exists():
            atomic(output / "FAILED-thread.json", {"reason": str(error), "full_acceptance": False})
        if campaign is not None:
            campaign.close("failed", {"reason": str(error)})
        raise
    finally:
        if campaign is not None:
            atomic(output / "ACTIVE_USAGE.json", {"closed": True, "active_seconds": time.monotonic() - campaign.start, "maximum_active_seconds": scope["maximum_active_seconds"]})
        quota.uninstall()
        quota.update(lambda state: state.update(closed=True))
        lease.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--scope", type=Path, required=True)
    parser.add_argument("--stage", choices=["produce", "independent", "fixture"])
    args = parser.parse_args()
    if args.stage:
        bootstrap(args.scope.resolve(), args.stage)
    else:
        execute(args.scope.resolve())
