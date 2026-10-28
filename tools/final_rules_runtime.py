"""Fresh full saved-actor rules evidence with bounded journals and native starts."""

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
from tools import parallel_storage_quota as storage
from tools.final_draw_runtime import copy_file, digest, load_scope, specification

JOURNAL_LIMIT = 512 * 1024**2


class RulesFile(storage.ReservedFile):
    def write(self, data):
        with self.lock:
            size = len(data) if self.binary else len(data.encode(self.stream.encoding or "utf-8"))
            end = self.stream.tell() + size
            maximum = self.quota.spec["journal_limit_bytes"] if self.kind == "data" else 40 * 1024**2
            if end > maximum:
                raise storage.StorageLimit("rules individual file ceiling exhausted")
            if end > self.credit:
                extra = self.quota.reserve(self.kind, self.key, end - self.credit if self.kind == "data" else end)
                self.credit = self.credit + extra if self.kind == "data" else extra
            return self.stream.write(data)

    def seek(self, offset, whence=0):
        current = self.stream.tell()
        size = os.fstat(self.stream.fileno()).st_size
        target = offset if whence == 0 else (current + offset if whence == 1 else size + offset)
        if whence not in (0, 1, 2) or target > max(size, current):
            raise storage.StorageLimit("rules sparse seek growth rejected")
        return self.stream.seek(offset, whence)


class RulesQuota(storage.Quota):
    def classify(self, path, *, replacement=False):
        path = Path(path).absolute()
        if path != path.resolve() or not path.is_relative_to(self.output):
            raise storage.StorageLimit("rules output escaped its scope")
        name = str(path.relative_to(self.output))
        if name in {"producer/observations.jsonl", "independent/native-observations.jsonl"}:
            if path.exists():
                raise storage.StorageLimit("rules committed journal is immutable")
            return "data", name
        canonical = name[:-4] if name.endswith(".tmp") else name
        root = {"WRITER.lock", "CONFIG.json", "COMMANDS.jsonl", "PROGRESS.json", "CAMPAIGN.json", "ACTIVE_USAGE.json", "FINAL_RULES.json", "FAILED-final-rules.json", "produce.log", "produce.json", "independent.log", "independent.json"}
        producer = {"summary.json"}
        independent = {"WRITER.lock", "CONFIG.json", "COMMANDS.jsonl", "PROGRESS.json", "CAMPAIGN.json", "RULES.json", "CLEANUP_FAILURE.json", "bin/caissa"}
        for row in self.spec["perft_ids"]:
            independent.update({"perft-" + row + ".json", "perft-" + row + ".log"})
        valid = canonical in root or canonical.startswith("producer/") and canonical[9:] in producer
        valid |= canonical.startswith("independent/") and canonical[12:] in independent
        if self.spec.get("fixture_mode"):
            valid |= canonical == "fixture.txt"
        if not valid:
            raise storage.StorageLimit("unknown rules evidence destination")
        return "control", name

    def opener(self, original):
        opening = super().opener(original)
        def open_file(*args, **kwargs):
            stream = opening(*args, **kwargs)
            if isinstance(stream, storage.ReservedFile):
                return RulesFile(self, stream.stream, stream.kind, stream.key, stream.credit, stream.binary)
            return stream
        return open_file


def close_rules_probe(probe):
    """Reap this contained native child and reject unexpected transport output."""
    if getattr(probe, "rules_closed", False):
        return
    probe.rules_closed = True
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
    error = bytes(probe.stderr) + (probe.process.stderr.read(1048577) or b"")
    extra = probe.buffer + (probe.process.stdout.read(16385) or b"")
    for stream in (probe.process.stdout, probe.process.stderr):
        stream.close()
    probe.reader.close()
    probe.writer.close()
    if probe.process.returncode != 0 or error or extra:
        raise ValueError("rules native transport failed or required forced cleanup")


def install_native_boundary(scope, quota, module):
    """Match every native command, count it before launch and contain its group."""
    from tools.campaign_process import Campaign
    original_popen, original_run = subprocess.Popen, Campaign.run
    copied = Path(scope["output"]) / "independent/bin/caissa"
    if scope.get("fixture_mode"):
        inventory = {tuple(command): key for key, command in scope["fixture_commands"].items()}
    elif module == "tools.differential":
        inventory = {(scope["engine"], "--inspect"): "produce-inspect"}
    else:
        inventory = {(str(copied), "--inspect"): "replay-inspect"}
        fixtures = json.loads((ROOT / "config/perft.json").read_text())
        for row in fixtures["positions"]:
            command = (str(copied), "--perft", str(row["depth"]), row["fen"])
            if row["chess960"]:
                command += ("960",)
            inventory[command] = "perft-" + row["id"]
    processes = []
    def popen(command, *args, **kwargs):
        key = inventory.get(tuple(command))
        if key is None:
            raise ValueError("unadmitted rules subprocess command")
        if not scope.get("fixture_mode") and digest(command[0]) != scope["engine_sha256"]:
            raise ValueError("rules native executable changed")
        if kwargs.get("stdout") != subprocess.PIPE or kwargs.get("stderr") not in (None, subprocess.PIPE, subprocess.STDOUT):
            raise ValueError("rules native output must use owned pipes")
        def count(state):
            names = state.setdefault("native_commands", [])
            if key in names or len(names) >= scope["maximum_native_actor_starts"]:
                raise storage.StorageLimit("rules native command/start allowance exhausted")
            names.append(key)
            state["native_starts"] = len(names)
        quota.update(count)
        kwargs["start_new_session"] = False
        if kwargs.get("stderr") is None:
            kwargs["stderr"] = subprocess.PIPE
        process = original_popen(command, *args, **kwargs)
        if os.getpgid(process.pid) != os.getpgrp():
            process.kill()
            process.wait(timeout=3)
            raise ValueError("rules native actor escaped its stage group")
        processes.append(process)
        return process
    def run(campaign, stage, command, *args, **kwargs):
        if tuple(command) not in inventory or not inventory[tuple(command)].startswith("perft-"):
            raise ValueError("unadmitted nested rules stage")
        kwargs["new_session"] = False
        return original_run(campaign, stage, command, *args, **kwargs)
    subprocess.Popen, Campaign.run = popen, run
    return processes, (original_popen, original_run)


def bootstrap(path, module, arguments):
    scope = load_scope(path)
    from tools.host_lease import inherited
    if not inherited(ROOT / "runs/TIMED_STRENGTH.lock"):
        raise ValueError("rules child lacks inherited actual host lease")
    file_limit = scope["fixture_file_limit_bytes"] if scope.get("fixture_mode") else JOURNAL_LIMIT
    resource.setrlimit(resource.RLIMIT_FSIZE, (file_limit, file_limit))
    quota = RulesQuota(specification(scope, path))
    quota.install()
    if module == "fixture" and scope.get("fixture_mode"):
        (Path(scope["output"]) / "fixture.txt").write_text("rules inherited bootstrap\n")
        return
    if module not in {"tools.differential", "verification.rules"} or scope.get("fixture_mode"):
        raise ValueError("rules module differs from admitted inventory")
    import verification.tactical_generation as transport
    transport.Probe.close = close_rules_probe
    shutil.copyfile = copy_file
    processes, _ = install_native_boundary(scope, quota, module)
    def interrupt(*_):
        raise InterruptedError("rules stage termination requested")
    signal.signal(signal.SIGTERM, interrupt)
    sys.argv = [module, *arguments]
    try:
        runpy.run_module(module, run_name="__main__")
    finally:
        for process in processes:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=3)
                raise ValueError("rules native process did not close normally")
            if process.returncode != 0:
                raise ValueError("rules native process exited nonzero")
            if process.stderr is not None and not process.stderr.closed:
                if process.stderr.read(1048577):
                    raise ValueError("rules native stderr is not empty")
                process.stderr.close()


def execute(path):
    scope = load_scope(path)
    if scope.get("fixture_mode") or scope["maximum_native_actor_starts"] != 22 or scope["journal_limit_bytes"] != JOURNAL_LIMIT:
        raise ValueError("rules full endpoint/start/file inventory differs")
    from tools.host_lease import HostLease
    from tools.campaign_process import Campaign, atomic
    from tools.storage_budget import footprint
    lease = HostLease(ROOT / "runs")
    quota = RulesQuota(specification(scope, path))
    quota.create()
    resource.setrlimit(resource.RLIMIT_FSIZE, (65536, JOURNAL_LIMIT))
    quota.install()
    output, campaign, last_check = Path(scope["output"]), None, 0
    def guard(force=False):
        nonlocal last_check
        lease.check()
        state = quota.read()
        if state.get("failure"):
            raise ValueError("rules storage failure latched")
        if force or time.monotonic() - last_check >= 5:
            actual = footprint([ROOT, *map(Path, scope["external_paths"])])
            storage.check_admission(actual["charged_bytes"], shutil.disk_usage(ROOT).used, scope["data_bytes"] - state["data_used"], scope["control_bytes"] - state["control_used"], scope["reserve_bytes"])
            last_check = time.monotonic()
    try:
        guard(True)
        campaign = Campaign(output, {"schema": "caissa-saved-actor-rules-runtime-v1", "scope_sha256": digest(path), "engine_sha256": scope["engine_sha256"], "match_games": 0}, scope["maximum_active_seconds"], absolute_deadline=scope["deadline_unix"], resource_guard=guard)
        atomic(output / "ACTIVE_USAGE.json", {"closed": False, "active_seconds": 0, "maximum_active_seconds": scope["maximum_active_seconds"]})
        common = [str(Path(sys.executable)), "-B", "-P", str(Path(__file__).resolve()), "--scope", str(path), "--stage"]
        produce = ["--engine", scope["engine"], "--positions", "100000", "--seed", "1729", "--output", str(output / "producer")]
        campaign.run("produce", [*common, "tools.differential", "--", *produce], 600, maximum_output_bytes=32768, cwd=ROOT, env=lease.environment(), pass_fds=(lease.stream.fileno(),))
        observed = output / "producer/observations.jsonl"
        verify = ["--observations", str(observed), "--summary", str(output / "producer/summary.json"), "--engine", scope["engine"], "--expected-engine-sha256", scope["engine_sha256"], "--protocol", str(ROOT / "config/rules-replay-v1.json"), "--expected-protocol-sha256", scope["profile_sha256"], "--fixtures", str(ROOT / "config/perft.json"), "--expected-observations-sha256", digest(observed), "--maximum-seconds", "900", "--output", str(output / "independent")]
        campaign.run("independent", [*common, "verification.rules", "--", *verify], 900, maximum_output_bytes=32768, cwd=ROOT, env=lease.environment(), pass_fds=(lease.stream.fileno(),))
        result = json.loads((output / "independent/RULES.json").read_text())
        if result["status"] != "passed" or not result["full_gate"] or result["positions"] != 100000 or len(result["perft"]) != 20 or result["engine_sha256"] != scope["engine_sha256"] or quota.read()["native_starts"] != 22:
            raise ValueError("saved-actor rules endpoint differs")
        atomic(output / "FINAL_RULES.json", {"status": "passed_saved_actor_rules_component", "engine_sha256": scope["engine_sha256"], "reader_sha256": digest(output / "independent/RULES.json"), "positions": 100000, "perft_positions": 20, "match_games": 0, "full_acceptance": False, "full_bundle_coordinator_executed": False})
        campaign.close("passed-component")
    except BaseException as error:
        if output.exists():
            atomic(output / "FAILED-final-rules.json", {"reason": str(error), "full_acceptance": False})
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
            parser.error("unadmitted rules owner arguments")
        execute(args.scope.resolve())
