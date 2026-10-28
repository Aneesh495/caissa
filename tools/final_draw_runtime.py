"""One prospectively scoped saved-actor draw-history check, never a game run."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import resource
import runpy
import shutil
import signal
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools import parallel_storage_quota as storage


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


class DrawQuota(storage.Quota):
    def classify(self, path, *, replacement=False):
        path = Path(path).absolute()
        if path != path.resolve() or not path.is_relative_to(self.output):
            raise storage.StorageLimit("draw output escaped its exact scope")
        name = str(path.relative_to(self.output))
        canonical = name[:-4] if name.endswith(".tmp") else name
        root_names = {
            "WRITER.lock", "CONFIG.json", "COMMANDS.jsonl", "PROGRESS.json",
            "CAMPAIGN.json", "ACTIVE_USAGE.json", "FINAL_DRAW.json",
            "FAILED-final-draw.json", "produce.log", "produce.json",
            "independent.log", "independent.json",
        }
        producer = {"profile.json", "CONFIG.json", "PROGRESS.json", "SUMMARY.json", "FAILED.json", "stderr.log", "observations.jsonl"}
        independent = {"caissa", "selected.cai", "DRAW_HISTORY.json", "PROGRESS.json", "FAILED.json", "stderr.log", "native-replay.jsonl"}
        valid = canonical in root_names
        valid |= canonical.startswith("producer/") and canonical[9:] in producer
        valid |= canonical.startswith("independent/") and canonical[12:] in independent
        if self.spec.get("fixture_mode"):
            valid |= canonical == "fixture.txt"
        if not valid:
            raise storage.StorageLimit("unknown draw evidence destination")
        if canonical.endswith("FAILED.json") or canonical.endswith("stderr.log"):
            return "control", "FAILED-" + name.replace("/", "-")
        return "control", name


def copy_file(source, target, *, follow_symlinks=True):
    """Keep the reader's actual saved-image copy inside metered Python writes."""
    source, target = Path(source), Path(target)
    if source.is_symlink() or source.stat().st_size > 4 * 1024**2:
        raise ValueError("draw saved-image copy input differs")
    before = source.stat()
    with source.open("rb") as reader, target.open("xb") as writer:
        for block in iter(lambda: reader.read(65536), b""):
            writer.write(block)
    after = source.stat()
    if (before.st_ino, before.st_size, before.st_mtime_ns) != (after.st_ino, after.st_size, after.st_mtime_ns):
        raise ValueError("draw copy source changed")
    return str(target)


def close_probe(probe):
    """Native actors inherit the stage group; close only this owned child."""
    probe.process.stdin.close()
    try:
        probe.process.wait(timeout=1)
    except subprocess.TimeoutExpired:
        probe.process.terminate()
        try:
            probe.process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            probe.process.kill()
            probe.process.wait(timeout=3)
    for stream in [probe.process.stdout, probe.process.stderr]:
        stream.close()
    probe.reader.close()
    probe.writer.close()


def load_scope(path):
    scope = json.loads(Path(path).read_text())
    if scope["status"] != "admitted" or time.time() >= scope["deadline_unix"]:
        raise ValueError("new draw scope is not admitted or live")
    for name, expected in scope["source_bindings"].items():
        if digest(ROOT / name) != expected:
            raise ValueError("draw source/input binding changed: " + name)
    if str(Path(sys.executable).resolve()) != scope["interpreter"] or digest(scope["interpreter"]) != scope["interpreter_sha256"]:
        raise ValueError("draw interpreter changed")
    return scope


def specification(scope, path):
    return {**scope, "scope_sha256": digest(path)}


def bootstrap(path, module, arguments):
    scope = load_scope(path)
    from tools.host_lease import inherited
    if not inherited(ROOT / "runs/TIMED_STRENGTH.lock"):
        raise ValueError("draw child lacks actual inherited host lease")
    resource.setrlimit(resource.RLIMIT_FSIZE, (40 * 1024**2, 40 * 1024**2))
    quota = DrawQuota(specification(scope, path))
    quota.install()
    if module == "fixture" and scope.get("fixture_mode"):
        (Path(scope["output"]) / "fixture.txt").write_text("actual inherited bootstrap\n")
        return
    if module not in {"tools.draw_history", "verification.draw_history"} or scope.get("fixture_mode"):
        raise ValueError("draw stage differs from exact admitted inventory")
    import verification.tactical_generation as transport
    original_popen = subprocess.Popen

    def native_popen(command, *args, **kwargs):
        image = Path(command[0]).resolve()
        allowed = {Path(scope["engine"]).resolve(), Path(scope["output"]) / "independent/caissa"}
        if image in allowed:
            if digest(image) != scope["engine_sha256"]:
                raise ValueError("draw native actor changed")
            def count(state):
                state["native_starts"] = state.get("native_starts", 0) + 1
                if state["native_starts"] > 2:
                    raise storage.StorageLimit("draw native start allowance exhausted")
            quota.update(count)
            kwargs["start_new_session"] = False
        elif Path(command[0]).name != "git" or command[1:] != ["rev-parse", "HEAD"]:
            raise ValueError("unadmitted draw subprocess")
        process = original_popen(command, *args, **kwargs)
        if image in allowed and os.getpgid(process.pid) != os.getpgrp():
            process.kill()
            process.wait(timeout=3)
            raise ValueError("draw native actor escaped its owned stage group")
        return process

    subprocess.Popen = native_popen
    transport.Probe.close = close_probe
    shutil.copyfile = copy_file
    def interrupt(*_):
        raise InterruptedError("draw stage termination requested")
    signal.signal(signal.SIGTERM, interrupt)
    sys.argv = [module, *arguments]
    runpy.run_module(module, run_name="__main__")


def execute(path):
    scope = load_scope(path)
    if scope.get("fixture_mode"):
        raise ValueError("fixture does not admit native execution")
    from tools.host_lease import HostLease
    from tools.campaign_process import Campaign, atomic
    from tools.storage_budget import footprint
    lease = HostLease(ROOT / "runs")
    spec = specification(scope, path)
    quota = DrawQuota(spec)
    quota.create()
    resource.setrlimit(resource.RLIMIT_FSIZE, (65536, 40 * 1024**2))
    quota.install()
    output = Path(scope["output"])
    campaign = None
    last_check = 0
    def guard(force=False):
        nonlocal last_check
        lease.check()
        state = quota.read()
        if state.get("failure"):
            raise ValueError("draw storage failure latched")
        if force or time.monotonic() - last_check >= 5:
            actual = footprint([ROOT, *map(Path, scope["external_paths"])])
            storage.check_admission(actual["charged_bytes"], shutil.disk_usage(ROOT).used, 0, scope["control_bytes"] - state["control_used"], scope["reserve_bytes"])
            last_check = time.monotonic()
    try:
        guard(True)
        campaign = Campaign(output, {"schema": "caissa-saved-actor-draw-runtime-v1", "scope_sha256": spec["scope_sha256"], "engine_sha256": scope["engine_sha256"], "games": 0}, scope["maximum_active_seconds"], absolute_deadline=scope["deadline_unix"], resource_guard=guard)
        atomic(output / "ACTIVE_USAGE.json", {"closed": False, "active_seconds": 0, "maximum_active_seconds": scope["maximum_active_seconds"]})
        common = [str(Path(sys.executable)), "-B", "-P", str(Path(__file__).resolve()), "--scope", str(path), "--stage"]
        profile = str(ROOT / "config/draw-history-v2.json")
        produce = ["--engine", scope["engine"], "--network", scope["network"], "--profile", profile, "--expected-profile-sha256", scope["profile_sha256"], "--output", str(output / "producer")]
        campaign.run("produce", [*common, "tools.draw_history", "--", *produce], 180, maximum_output_bytes=32768, cwd=ROOT, env=lease.environment(), pass_fds=(lease.stream.fileno(),))
        observed = output / "producer/observations.jsonl"
        verify = ["--observations", str(observed), "--summary", str(output / "producer/SUMMARY.json"), "--config", str(output / "producer/CONFIG.json"), "--engine", scope["engine"], "--network", scope["network"], "--profile", profile, "--output", str(output / "independent"), "--expected-engine-sha256", scope["engine_sha256"], "--expected-network-sha256", scope["network_sha256"], "--expected-profile-sha256", scope["profile_sha256"], "--expected-observations-sha256", digest(observed), "--maximum-seconds", "240"]
        campaign.run("independent", [*common, "verification.draw_history", "--", *verify], 240, maximum_output_bytes=32768, cwd=ROOT, env=lease.environment(), pass_fds=(lease.stream.fileno(),))
        result = json.loads((output / "independent/DRAW_HISTORY.json").read_text())
        if result["status"] != "passed" or result["engine_sha256"] != scope["engine_sha256"] or result["histories"] != 92 or result["observations"] != 2195:
            raise ValueError("saved-actor draw endpoint differs")
        atomic(output / "FINAL_DRAW.json", {"status": "passed_saved_actor_draw_component", "engine_sha256": scope["engine_sha256"], "network_sha256": scope["network_sha256"], "reader_sha256": digest(output / "independent/DRAW_HISTORY.json"), "histories": 92, "observations": 2195, "games": 0, "full_acceptance": False, "full_bundle_coordinator_executed": False})
        campaign.close("passed-component")
    except BaseException as error:
        if output.exists():
            atomic(output / "FAILED-final-draw.json", {"reason": str(error), "full_acceptance": False})
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
    parser.add_argument("--stage")
    args, tail = parser.parse_known_args()
    if tail[:1] == ["--"]:
        tail = tail[1:]
    if args.stage:
        bootstrap(args.scope.resolve(), args.stage, tail)
    else:
        if tail:
            parser.error("unadmitted owner arguments")
        execute(args.scope.resolve())
