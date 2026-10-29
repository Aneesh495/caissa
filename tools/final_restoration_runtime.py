"""Run the missing saved-actor restoration sample using lossless scoped journals."""

import argparse
import json
import os
from pathlib import Path
import resource
import runpy
import shutil
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools import parallel_storage_quota as storage
from tools.final_draw_runtime import copy_file, digest, load_scope, specification
from tools.final_rules_runtime import RulesFile, close_rules_probe
from tools.restoration_journal import open_journal


class RestorationQuota(storage.Quota):
    def classify(self, path, *, replacement=False):
        p = Path(path).absolute()
        if p != p.resolve() or not p.is_relative_to(self.output):
            raise storage.StorageLimit("restoration output escaped its scope")
        name = str(p.relative_to(self.output))
        data = {"producer/observations.jsonl.gz", "independent/native-replay.jsonl.gz"}
        if self.spec.get("fixture_mode"):
            data |= {"roundtrip.gz", "corrupt.gz", "truncated.gz", "plain.jsonl"}
        if name in data:
            if p.exists():
                raise storage.StorageLimit("restoration journal is immutable")
            return "data", name
        canonical = name[:-4] if name.endswith(".tmp") else name
        root = {"WRITER.lock", "CONFIG.json", "COMMANDS.jsonl", "PROGRESS.json", "CAMPAIGN.json", "ACTIVE_USAGE.json", "FINAL_RESTORATION.json", "FAILED-final-restoration.json", "produce.log", "produce.json", "independent.log", "independent.json"}
        producer = {"CONFIG.json", "SUMMARY.json", "PROGRESS.json", "FAILED.json", "native-stderr.log"}
        independent = {"CONFIG.json", "PROGRESS.json", "FAILED.json", "RESTORATION.json", "native-stderr.log", "caissa", "selected.cai"}
        valid = canonical in root or canonical.startswith("producer/") and canonical[9:] in producer
        valid |= canonical.startswith("independent/") and canonical[12:] in independent
        if not valid:
            raise storage.StorageLimit("unknown restoration evidence destination")
        if canonical.endswith(("FAILED.json", "native-stderr.log")):
            return "control", "FAILED-" + name.replace("/", "-")
        return "control", name

    def opener(self, original):
        opening = super().opener(original)
        def open_file(*args, **kwargs):
            stream = opening(*args, **kwargs)
            if isinstance(stream, storage.ReservedFile):
                return RulesFile(self, stream.stream, stream.kind, stream.key, stream.credit, stream.binary)
            return stream
        return open_file


def bootstrap(path, module, arguments):
    scope = load_scope(path)
    from tools.host_lease import inherited
    if not inherited(ROOT / "runs/TIMED_STRENGTH.lock"):
        raise ValueError("restoration child lacks inherited host lease")
    resource.setrlimit(resource.RLIMIT_FSIZE, (512 * 1024**2, 512 * 1024**2))
    quota = RestorationQuota(specification(scope, path))
    quota.install()
    if module == "fixture" and scope.get("fixture_mode"):
        p = Path(scope["output"]) / "producer/observations.jsonl.gz"
        with open_journal(p, "xb", compressed=True, maximum_bytes=1024) as stream:
            stream.write(b"inherited restoration journal\n")
        return
    if module not in {"tools.restoration", "verification.restoration"} or scope.get("fixture_mode"):
        raise ValueError("restoration stage was not admitted")
    import verification.tactical_generation as transport
    transport.Probe.close = close_rules_probe
    shutil.copyfile = copy_file
    original = subprocess.Popen
    if module == "tools.restoration":
        command = [scope["engine"], "--state-probe", scope["network"]]
    else:
        command = [str(Path(scope["output"]) / "independent/caissa"), "--state-probe", str(Path(scope["output"]) / "independent/selected.cai")]
    def popen(argv, *args, **kwargs):
        if list(argv) == ["git", "show", scope["product_commit"] + ":tools/restoration.py"]:
            return original(argv, *args, **kwargs)
        if list(argv) != command or digest(argv[0]) != scope["engine_sha256"]:
            raise ValueError("unadmitted restoration subprocess")
        if any(kwargs.get(key) != subprocess.PIPE for key in ["stdin", "stdout", "stderr"]):
            raise ValueError("restoration native actor must use owned pipes")
        def count(state):
            names = state.setdefault("native_commands", [])
            if module in names or len(names) >= 2:
                raise storage.StorageLimit("restoration native start allowance exhausted")
            names.append(module)
            state["native_starts"] = len(names)
        quota.update(count)
        kwargs["start_new_session"] = False
        process = original(argv, *args, **kwargs)
        if os.getpgid(process.pid) != os.getpgrp():
            process.kill()
            process.wait(timeout=3)
            raise ValueError("restoration actor escaped its stage group")
        return process
    subprocess.Popen = popen
    sys.argv = [module, *arguments]
    runpy.run_module(module, run_name="__main__")


def execute(path):
    scope = load_scope(path)
    if scope.get("fixture_mode") or scope["maximum_native_actor_starts"] != 2:
        raise ValueError("restoration runtime inventory differs")
    from tools.host_lease import HostLease
    from tools.campaign_process import Campaign, atomic
    from tools.storage_budget import footprint
    lease = HostLease(ROOT / "runs")
    quota = RestorationQuota(specification(scope, path))
    quota.create()
    resource.setrlimit(resource.RLIMIT_FSIZE, (65536, 512 * 1024**2))
    quota.install()
    output, campaign, last_check = Path(scope["output"]), None, 0
    def guard(force=False):
        nonlocal last_check
        lease.check()
        state = quota.read()
        if state.get("failure"):
            raise ValueError("restoration storage failure latched")
        if force or time.monotonic() - last_check >= 5:
            actual = footprint([ROOT, *map(Path, scope["external_paths"])])
            storage.check_admission(actual["charged_bytes"], shutil.disk_usage(ROOT).used, scope["data_bytes"] - state["data_used"], scope["control_bytes"] - state["control_used"], scope["reserve_bytes"])
            last_check = time.monotonic()
    try:
        guard(True)
        campaign = Campaign(output, {"schema": "caissa-saved-actor-restoration-runtime-v1", "scope_sha256": digest(path), "engine_sha256": scope["engine_sha256"], "network_sha256": scope["network_sha256"], "match_games": 0, "journal_encoding": "gzip-v1"}, scope["maximum_active_seconds"], absolute_deadline=scope["deadline_unix"], resource_guard=guard)
        atomic(output / "ACTIVE_USAGE.json", {"closed": False, "active_seconds": 0, "maximum_active_seconds": scope["maximum_active_seconds"]})
        common = [str(Path(sys.executable)), "-B", "-P", str(Path(__file__).resolve()), "--scope", str(path), "--stage"]
        shared = ["--engine", scope["engine"], "--network", scope["network"], "--profile", str(ROOT / "config/restoration-v1.json"), "--expected-profile-sha256", scope["profile_sha256"], "--gzip-journals"]
        producer = [*shared, "--pairs", "1000000", "--maximum-seconds", "1800", "--source-commit", scope["product_commit"], "--output", str(output / "producer")]
        campaign.run("produce", [*common, "tools.restoration", "--", *producer], 1810, maximum_output_bytes=32768, cwd=ROOT, env=lease.environment(), pass_fds=(lease.stream.fileno(),))
        summary = json.loads((output / "producer/SUMMARY.json").read_text())
        independent = [*shared, "--observations", str(output / "producer/observations.jsonl.gz"), "--summary", str(output / "producer/SUMMARY.json"), "--config", str(output / "producer/CONFIG.json"), "--expected-engine-sha256", scope["engine_sha256"], "--expected-network-sha256", scope["network_sha256"], "--expected-observations-sha256", summary["observations_sha256"], "--mode", "full", "--maximum-seconds", "3600", "--output", str(output / "independent")]
        campaign.run("independent", [*common, "verification.restoration", "--", *independent], 3610, maximum_output_bytes=32768, cwd=ROOT, env=lease.environment(), pass_fds=(lease.stream.fileno(),))
        result = json.loads((output / "independent/RESTORATION.json").read_text())
        if result["status"] != "passed" or not result["full_gate"] or result["pairs"] != 1000000 or result["engine_sha256"] != scope["engine_sha256"] or quota.read()["native_starts"] != 2:
            raise ValueError("saved-actor full restoration endpoint differs")
        atomic(output / "FINAL_RESTORATION.json", {"status": "passed_saved_actor_restoration_component", "reader_sha256": digest(output / "independent/RESTORATION.json"), "pairs": result["pairs"], "engine_sha256": scope["engine_sha256"], "network_sha256": scope["network_sha256"], "match_games": 0, "full_acceptance": False, "full_bundle_coordinator_executed": False})
        campaign.close("passed-component")
    except BaseException as error:
        if output.exists():
            atomic(output / "FAILED-final-restoration.json", {"reason": str(error), "full_acceptance": False})
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
            parser.error("unadmitted restoration owner arguments")
        execute(args.scope.resolve())
