"""Fresh saved-actor numerical sample with prepaid native output descriptors."""

import argparse
import json
import os
from pathlib import Path
import re
import resource
import runpy
import shutil
import signal
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools import parallel_storage_quota as storage
from tools.final_draw_runtime import digest, load_scope, specification
from tools.final_rules_runtime import RulesFile

NATIVE_LIMIT = 128 * 1024**2
FILE_LIMITS = {
    "producer/POSITIONS.fen": 256 * 1024**2,
    "producer/probes.jsonl": 512 * 1024**2,
    "independent/native-output.jsonl": NATIVE_LIMIT,
    "independent/native-stderr.log": NATIVE_LIMIT,
}


class NumericalFile(RulesFile):
    def write(self, data):
        amount = len(data) if self.binary else len(data.encode(self.stream.encoding or "utf-8"))
        limit = self.quota.spec["file_limits"].get(self.key, 65536 if self.key.startswith("scratch/") else 40 * 1024**2)
        if self.stream.tell() + amount > limit:
            raise storage.StorageLimit("numerical per-file ceiling exhausted")
        return super().write(data)


class NumericalQuota(storage.Quota):
    def classify(self, path, *, replacement=False):
        path = Path(path).absolute()
        if path != path.resolve() or not path.is_relative_to(self.output):
            raise storage.StorageLimit("numerical output escaped its scope")
        name = str(path.relative_to(self.output))
        if name in self.spec["file_limits"]:
            if path.exists():
                raise storage.StorageLimit("numerical committed data file is immutable")
            return "data", name
        canonical = name[:-4] if name.endswith(".tmp") else name
        names = {"WRITER.lock", "CONFIG.json", "COMMANDS.jsonl", "PROGRESS.json", "CAMPAIGN.json", "ACTIVE_USAGE.json", "FINAL_NUMERICAL.json", "NUMERICAL_REPLAY.json", "FAILED-final-numerical.json", "produce.log", "produce.json", "independent.log", "independent.json", "producer/CONFIG.json", "producer/SUMMARY.json"}
        valid = canonical in names
        valid |= bool(re.fullmatch(r"scratch/[A-Za-z0-9_.-]{1,100}/[A-Za-z0-9_.-]{1,100}", canonical))
        valid |= self.spec.get("fixture_mode", False) and canonical == "fixture.json"
        if not valid:
            raise storage.StorageLimit("unknown numerical evidence destination")
        if canonical == "producer/SUMMARY.json":
            return "control", "FAILED-numerical-summary.json" + (".tmp" if name.endswith(".tmp") else "")
        return "control", name

    def opener(self, original):
        opening = super().opener(original)
        def open_file(*args, **kwargs):
            stream = opening(*args, **kwargs)
            if isinstance(stream, storage.ReservedFile):
                return NumericalFile(self, stream.stream, stream.kind, stream.key, stream.credit, stream.binary)
            return stream
        return open_file

    def install(self):
        super().install()
        self.original_mkdir = os.mkdir
        def mkdir(path, *args, **kwargs):
            p = Path(path).absolute()
            if p != p.resolve() or not p.is_relative_to(self.output):
                raise storage.StorageLimit("numerical directory escaped output")
            relative = str(p.relative_to(self.output))
            if relative not in {".", "producer", "independent", "scratch"}:
                if not re.fullmatch(r"scratch/[A-Za-z0-9_.-]{1,100}", relative):
                    raise storage.StorageLimit("unknown numerical scratch directory")
                if not p.exists():
                    def count(state):
                        state["scratch_directories"] = state.get("scratch_directories", 0) + 1
                        if state["scratch_directories"] > 16:
                            raise storage.StorageLimit("numerical scratch-directory ceiling exhausted")
                    self.update(count)
                    self.reserve("control", "scratch-directory-" + relative, 4096)
            return self.original_mkdir(path, *args, **kwargs)
        os.mkdir = mkdir

    def uninstall(self):
        if hasattr(self, "original_mkdir"):
            os.mkdir = self.original_mkdir
            del self.original_mkdir
        super().uninstall()


class NativeFiles:
    """Replace only the reader's two temporary files with retained scoped files."""
    def __init__(self, quota):
        self.quota, self.count = quota, 0

    def temporary(self):
        names = ["independent/native-output.jsonl", "independent/native-stderr.log"]
        if self.count >= len(names):
            raise storage.StorageLimit("numerical temporary-file inventory exhausted")
        path = self.quota.output / names[self.count]
        self.count += 1
        return path.open("w+b")


def prepay_native_files(quota, output, errors):
    for stream, key in [(output, "independent/native-output.jsonl"), (errors, "independent/native-stderr.log")]:
        if not isinstance(stream, NumericalFile) or stream.quota is not quota or stream.kind != "data" or stream.key != key:
            raise storage.StorageLimit("numerical native descriptor differs from reserved destination")
        maximum = quota.spec["native_file_limit_bytes"]
        if quota.spec["file_limits"][key] != maximum:
            raise storage.StorageLimit("numerical descriptor/file ceilings differ")
        if maximum > stream.credit:
            stream.credit += quota.reserve("data", key, maximum - stream.credit)


def install_native_boundary(scope, quota, module):
    original = subprocess.Popen
    if scope.get("fixture_mode"):
        allowed = {tuple(value): key for key, value in scope["fixture_commands"].items()}
    else:
        allowed = {(scope["engine"], "--net-probe", scope["network"]): module}
    processes = []
    def popen(command, *args, **kwargs):
        key = allowed.get(tuple(command))
        if key is None or not scope.get("fixture_mode") and digest(command[0]) != scope["engine_sha256"]:
            raise ValueError("unadmitted numerical subprocess")
        if module == "verification.numerical" or key == "descriptor":
            prepay_native_files(quota, kwargs["stdout"], kwargs["stderr"])
        elif kwargs.get("stdin") != subprocess.PIPE or kwargs.get("stdout") != subprocess.PIPE or kwargs.get("stderr") not in (None, subprocess.PIPE):
            raise ValueError("numerical producer must use owned pipes")
        def count(state):
            commands = state.setdefault("native_commands", [])
            if key in commands or len(commands) >= scope["maximum_native_actor_starts"]:
                raise storage.StorageLimit("numerical native start allowance exhausted")
            commands.append(key)
            state["native_starts"] = len(commands)
        quota.update(count)
        if kwargs.get("preexec_fn") is not None:
            raise ValueError("numerical native preexec was not admitted")
        def limit():
            size = scope["native_file_limit_bytes"]
            resource.setrlimit(resource.RLIMIT_FSIZE, (size, size))
        kwargs.update(start_new_session=False, preexec_fn=limit)
        if kwargs.get("stderr") is None:
            kwargs["stderr"] = subprocess.PIPE
        process = original(command, *args, **kwargs)
        if os.getpgid(process.pid) != os.getpgrp():
            process.kill()
            process.wait(timeout=3)
            raise ValueError("numerical native actor escaped stage group")
        processes.append(process)
        return process
    subprocess.Popen = popen
    return processes, original


def import_numerical_runtime():
    original = subprocess.Popen
    def reject(*_args, **_kwargs):
        raise ValueError("numerical dependency import may not launch subprocesses")
    subprocess.Popen = reject
    try:
        import torch
        import numpy
        import training.model
        import verification.numerical
        torch.set_num_threads(2)
        return torch, numpy, verification.numerical
    finally:
        subprocess.Popen = original


def bootstrap(path, module, arguments):
    scope = load_scope(path)
    from tools.host_lease import inherited
    if not inherited(ROOT / "runs/TIMED_STRENGTH.lock"):
        raise ValueError("numerical child lacks inherited host lease")
    resource.setrlimit(resource.RLIMIT_FSIZE, (512 * 1024**2, 512 * 1024**2))
    quota = NumericalQuota(specification(scope, path))
    quota.install()
    output = Path(scope["output"])
    (output / "scratch").mkdir(exist_ok=True)
    tempfile.tempdir = str(output / "scratch")
    torch, numpy, reader = import_numerical_runtime()
    if module == "fixture-import" and scope.get("fixture_mode"):
        from verification.learning import checkpoint
        state = checkpoint(Path(scope["checkpoint"]))
        (output / "fixture.json").write_text(json.dumps({"torch": str(torch.__version__), "numpy": numpy.__version__, "checkpoint_model_parameters": len(state["model"]), "inference": False}))
        return
    if module not in {"tools.network_audit", "verification.numerical"} or scope.get("fixture_mode"):
        raise ValueError("numerical module was not admitted")
    factory = NativeFiles(quota)
    if module == "verification.numerical":
        (output / "independent").mkdir()
        tempfile.TemporaryFile = factory.temporary
    processes, _ = install_native_boundary(scope, quota, module)
    def interrupt(*_):
        raise InterruptedError("numerical stage termination requested")
    signal.signal(signal.SIGTERM, interrupt)
    sys.argv = [module, *arguments]
    try:
        if module == "verification.numerical":
            code = reader.main()
            if code:
                raise SystemExit(code)
        else:
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
                raise ValueError("numerical native process required forced cleanup")
            if process.returncode != 0:
                raise ValueError("numerical native process exited nonzero")
            if process.stderr is not None and not process.stderr.closed:
                if process.stderr.read(1048577):
                    raise ValueError("numerical native stderr is not empty")
                process.stderr.close()
        if module == "verification.numerical" and ((output / "independent/native-stderr.log").stat().st_size or factory.count != 2):
            raise ValueError("numerical native file/transport inventory differs")


def execute(path):
    scope = load_scope(path)
    if scope.get("fixture_mode") or scope["file_limits"] != FILE_LIMITS or scope["native_file_limit_bytes"] != NATIVE_LIMIT or scope["maximum_native_actor_starts"] != 2:
        raise ValueError("numerical full sample/file/start inventory differs")
    from tools.host_lease import HostLease
    from tools.campaign_process import Campaign, atomic
    from tools.storage_budget import footprint
    lease = HostLease(ROOT / "runs")
    quota = NumericalQuota(specification(scope, path))
    quota.create()
    resource.setrlimit(resource.RLIMIT_FSIZE, (65536, 512 * 1024**2))
    quota.install()
    output, campaign, last_check = Path(scope["output"]), None, 0
    def guard(force=False):
        nonlocal last_check
        lease.check()
        state = quota.read()
        if state.get("failure"):
            raise ValueError("numerical storage failure latched")
        if force or time.monotonic() - last_check >= 5:
            actual = footprint([ROOT, *map(Path, scope["external_paths"])])
            storage.check_admission(actual["charged_bytes"], shutil.disk_usage(ROOT).used, scope["data_bytes"] - state["data_used"], scope["control_bytes"] - state["control_used"], scope["reserve_bytes"])
            last_check = time.monotonic()
    try:
        guard(True)
        campaign = Campaign(output, {"schema": "caissa-saved-actor-numerical-runtime-v1", "scope_sha256": digest(path), "engine_sha256": scope["engine_sha256"], "network_sha256": scope["network_sha256"], "checkpoint_sha256": scope["checkpoint_sha256"], "match_games": 0}, scope["maximum_active_seconds"], absolute_deadline=scope["deadline_unix"], resource_guard=guard)
        atomic(output / "ACTIVE_USAGE.json", {"closed": False, "active_seconds": 0, "maximum_active_seconds": scope["maximum_active_seconds"]})
        common = [str(Path(sys.executable)), "-B", "-P", str(Path(__file__).resolve()), "--scope", str(path), "--stage"]
        shared = ["--engine", scope["engine"], "--network", scope["network"], "--checkpoint", scope["checkpoint"]]
        produce = [*shared, "--export-format", "4", "--probes", "100000", "--seed", "32452867", "--maximum-error-cp", "32", "--max-seconds", "600", "--output", str(output / "producer")]
        env = {**lease.environment(), "TMPDIR": str(output / "scratch"), "TORCHINDUCTOR_CACHE_DIR": str(output / "scratch/inductor")}
        campaign.run("produce", [*common, "tools.network_audit", "--", *produce], 610, maximum_output_bytes=32768, cwd=ROOT, env=env, pass_fds=(lease.stream.fileno(),))
        verify = [str(output / "producer"), *shared, "--protocol", str(ROOT / "config/precision-v4.json"), "--require-full", "--expected-network-sha256", scope["network_sha256"], "--expected-checkpoint-sha256", scope["checkpoint_sha256"], "--max-seconds", "600", "--inherit-process-group"]
        campaign.run("independent", [*common, "verification.numerical", "--", *verify], 610, maximum_output_bytes=32768, cwd=ROOT, env=env, pass_fds=(lease.stream.fileno(),))
        result = json.loads((output / "independent.log").read_text())
        if result["status"] != "passed" or result["probes"] != 100000 or result["maximum_error_cp"] != 32 or result["engine_sha256"] != scope["engine_sha256"] or quota.read()["native_starts"] != 2:
            raise ValueError("saved-actor numerical endpoint differs")
        atomic(output / "NUMERICAL_REPLAY.json", result)
        atomic(output / "FINAL_NUMERICAL.json", {"status": "passed_saved_actor_numerical_component", "reader_sha256": digest(output / "NUMERICAL_REPLAY.json"), "probes": 100000, "engine_sha256": scope["engine_sha256"], "network_sha256": scope["network_sha256"], "checkpoint_sha256": scope["checkpoint_sha256"], "match_games": 0, "full_acceptance": False, "full_bundle_coordinator_executed": False})
        campaign.close("passed-component")
    except BaseException as error:
        if output.exists():
            atomic(output / "FAILED-final-numerical.json", {"reason": str(error), "full_acceptance": False})
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
            parser.error("unadmitted numerical owner arguments")
        execute(args.scope.resolve())
