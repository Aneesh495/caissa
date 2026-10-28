"""Fresh bounded saved-actor protocol evidence, separate from closed samples."""

import argparse
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
from tools.final_draw_runtime import digest, load_scope, specification
from tools.parallel_storage_quota import Quota, StorageLimit

NATIVE_FILE_LIMIT = 40 * 1024**2


class ProtocolQuota(Quota):
    def classify(self, path, *, replacement=False):
        path = Path(path).absolute()
        if path != path.resolve() or not path.is_relative_to(self.output):
            raise StorageLimit("protocol output escaped its scope")
        name = str(path.relative_to(self.output))
        canonical = name[:-4] if name.endswith(".tmp") else name
        root = {"WRITER.lock", "CONFIG.json", "COMMANDS.jsonl", "PROGRESS.json", "CAMPAIGN.json", "ACTIVE_USAGE.json", "FINAL_PROTOCOL.json", "PROTOCOL_REPLAY.json", "FAILED-final-protocol.json", "produce.log", "produce.json", "independent.log", "independent.json"}
        producer = {"CONFIG.json", "PROGRESS.json", "summary.json", "transcript.jsonl", "stderr.log"}
        valid = canonical in root or (canonical.startswith("producer/") and canonical[9:] in producer)
        if self.spec.get("fixture_mode"):
            valid |= canonical == "fixture.txt"
        if not valid:
            raise StorageLimit("unknown protocol evidence destination")
        if canonical == "producer/summary.json":
            return "control", "FAILED-protocol-summary.json" + (".tmp" if name.endswith(".tmp") else "")
        return "control", name


def reserve_native_stderr(quota, stream, maximum):
    if stream.quota is not quota or stream.key != "producer/stderr.log":
        raise StorageLimit("native descriptor is not its declared stderr stream")
    stream.credit = quota.reserve("control", stream.key, maximum)


def bootstrap(path, module, arguments):
    scope = load_scope(path)
    from tools.host_lease import inherited
    if not inherited(ROOT / "runs/TIMED_STRENGTH.lock"):
        raise ValueError("protocol child lacks inherited actual host lease")
    resource.setrlimit(resource.RLIMIT_FSIZE, (NATIVE_FILE_LIMIT, NATIVE_FILE_LIMIT))
    quota = ProtocolQuota(specification(scope, path))
    quota.install()
    if module == "fixture" and scope.get("fixture_mode"):
        (Path(scope["output"]) / "fixture.txt").write_text("protocol inherited bootstrap\n")
        return
    if module not in {"tools.protocol_campaign", "verification.protocol"} or scope.get("fixture_mode"):
        raise ValueError("protocol module was not admitted")
    if scope["native_file_limit_bytes"] != NATIVE_FILE_LIMIT:
        raise ValueError("native file limit differs from reserved descriptor bound")
    original = subprocess.Popen
    def native_popen(command, *args, **kwargs):
        if Path(command[0]).resolve() != Path(scope["engine"]).resolve() or digest(command[0]) != scope["engine_sha256"]:
            raise ValueError("unadmitted protocol subprocess")
        reserve_native_stderr(quota, kwargs["stderr"], NATIVE_FILE_LIMIT)
        def count(state):
            state["native_starts"] = state.get("native_starts", 0) + 1
            if state["native_starts"] > 1:
                raise StorageLimit("protocol native start allowance exhausted")
        quota.update(count)
        kwargs["start_new_session"] = False
        process = original(command, *args, **kwargs)
        if os.getpgid(process.pid) != os.getpgrp():
            process.kill()
            process.wait(timeout=3)
            raise ValueError("protocol native actor escaped its stage group")
        return process
    subprocess.Popen = native_popen
    def interrupt(*_):
        raise InterruptedError("protocol stage termination requested")
    signal.signal(signal.SIGTERM, interrupt)
    sys.argv = [module, *arguments]
    runpy.run_module(module, run_name="__main__")


def execute(path):
    scope = load_scope(path)
    if scope.get("fixture_mode"):
        raise ValueError("fixture does not admit protocol actors")
    from tools.host_lease import HostLease
    from tools.campaign_process import Campaign, atomic
    from tools.storage_budget import footprint, admission
    lease = HostLease(ROOT / "runs")
    quota = ProtocolQuota(specification(scope, path))
    quota.create()
    resource.setrlimit(resource.RLIMIT_FSIZE, (65536, NATIVE_FILE_LIMIT))
    quota.install()
    output, campaign, last_check = Path(scope["output"]), None, 0
    def guard(force=False):
        nonlocal last_check
        lease.check()
        state = quota.read()
        if state.get("failure"):
            raise ValueError("protocol storage failure latched")
        if force or time.monotonic() - last_check >= 5:
            actual = footprint([ROOT, *map(Path, scope["external_paths"])])
            admission(actual["charged_bytes"], shutil.disk_usage(ROOT).used, scope["control_bytes"] - state["control_used"], scope["reserve_bytes"])
            last_check = time.monotonic()
    try:
        guard(True)
        campaign = Campaign(output, {"schema": "caissa-new-saved-actor-protocol-v1", "scope_sha256": digest(path), "engine_sha256": scope["engine_sha256"], "match_games": 0}, scope["maximum_active_seconds"], absolute_deadline=scope["deadline_unix"], resource_guard=guard)
        atomic(output / "ACTIVE_USAGE.json", {"closed": False, "active_seconds": 0, "maximum_active_seconds": scope["maximum_active_seconds"]})
        common = [str(Path(sys.executable)), "-B", "-P", str(Path(__file__).resolve()), "--scope", str(path), "--stage"]
        produce = ["--engine", scope["engine"], "--sequences", "10000", "--max-seconds", "900", "--output", str(output / "producer")]
        campaign.run("produce", [*common, "tools.protocol_campaign", "--", *produce], 900, maximum_output_bytes=32768, cwd=ROOT, env=lease.environment(), pass_fds=(lease.stream.fileno(),))
        if (output / "producer/stderr.log").stat().st_size:
            raise ValueError("protocol native stderr is not empty")
        verify = [str(output / "producer"), "--engine", scope["engine"], "--full"]
        campaign.run("independent", [*common, "verification.protocol", "--", *verify], 240, maximum_output_bytes=32768, cwd=ROOT, env=lease.environment(), pass_fds=(lease.stream.fileno(),))
        result = json.loads((output / "independent.log").read_text())
        if result["status"] != "passed" or result["engine_sha256"] != scope["engine_sha256"] or result["completed"] != 10000 or result["ponder_completed"] != 100:
            raise ValueError("saved-actor protocol endpoint differs")
        atomic(output / "PROTOCOL_REPLAY.json", result)
        atomic(output / "FINAL_PROTOCOL.json", {"status": "passed_saved_actor_protocol_component", "engine_sha256": scope["engine_sha256"], "reader_sha256": digest(output / "PROTOCOL_REPLAY.json"), "ordinary_sequences": 10000, "ponder_sequences": 100, "match_games": 0, "full_acceptance": False, "full_bundle_coordinator_executed": False})
        campaign.close("passed-component")
    except BaseException as error:
        if output.exists():
            atomic(output / "FAILED-final-protocol.json", {"reason": str(error), "full_acceptance": False})
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
            parser.error("unadmitted protocol owner arguments")
        execute(args.scope.resolve())
