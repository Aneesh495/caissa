"""One prospective final-adapter integration and real full-entry invocation."""

import copy
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


def require(value, reason):
    if not value:
        raise ValueError(reason)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read(path):
    return json.loads(Path(path).read_text())


def entry(scope_path):
    """The actual full CLI runs with no writable regular-file allowance."""
    scope = read(scope_path)
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    resource.setrlimit(resource.RLIMIT_FSIZE, (0, 0))
    commands = []
    inactive_locks = {str(ROOT / "runs" / n / "OWNER.lock") for n in ["full-neural-strength-v3", "full-external-strength-v3", "full-neural-strength-v4", "full-external-strength-v4"]}

    def audit(event, args):
        if event.startswith("socket.") or event in {"os.system", "os.posix_spawn", "os.exec", "os.link", "os.symlink", "os.remove", "os.rename", "os.mkdir"}:
            raise ValueError("full-entry bootstrap permits no network or mutation")
        if event == "subprocess.Popen":
            command = args[1]
            allowed = command in [["git", "rev-parse", "HEAD"], ["git", "cat-file", "--batch"], ["git", "ls-tree", "-r", "-l", "-z", "--full-tree", scope["product_commit"]]]
            require(allowed and len(commands) < 4, "only exact read-only source Git calls admitted")
            commands.append(command)
        if event == "open":
            name, mode, flags = args
            writing = isinstance(mode, str) and any(c in mode for c in "wax+") or isinstance(flags, int) and flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND)
            if writing:
                if name == os.devnull:
                    return
                # Existing old OWNER locks are opened only for flock by the
                # unchanged guard. RLIMIT_FSIZE=0 forbids any content append.
                require(isinstance(name, str) and str(Path(name).absolute()) in inactive_locks and mode == "a" and Path(name).is_file() and Path(name).stat().st_size == 0, "full-entry regular-file write rejected: " + repr((name, mode, flags)))
    sys.addaudithook(audit)
    fixture = Path(scope["output"]) / "fixture"
    sys.argv = ["verification.full_bundle", str(fixture), "--checkout", str(ROOT), "--expected-commit", scope["product_commit"], "--expected-inputs-sha256", sha(fixture / "FULL_INPUTS.json"), "--maximum-seconds", "30"]
    runpy.run_module("verification.full_bundle", run_name="__main__")


def main(scope_path):
    os.umask(0o077)
    from tools import parallel_storage_quota as storage
    from tools.campaign_process import Campaign, StageFailure, atomic
    from tools.host_lease import HostLease
    from tools.storage_budget import footprint
    from verification.bundle import Bundle
    from verification.final_evidence_bundle import DRIVERS, integrate, verify
    from verification.source import PRODUCT, snapshot

    path = Path(scope_path).resolve()
    scope = read(path)
    work, output = path.parent, Path(scope["output"])
    require(scope["status"] == "admitted" and time.time() < scope["deadline_unix"] and not (work / "STARTED.json").exists(), "one fresh adapter invocation required")
    for name, digest in scope["source_bindings"].items():
        target = ROOT / name
        require(target.resolve() == target and target.is_file() and sha(target) == digest, "adapter source/input changed: " + name)
    require(str(Path(sys.executable).resolve()) == scope["interpreter"] and sha(sys.executable) == scope["interpreter_sha256"], "adapter Python differs")
    lease = HostLease(ROOT / "runs")
    work.joinpath("STARTED.json").write_text(json.dumps({"unix": time.time()}) + "\n")
    class AdapterQuota(storage.Quota):
        def classify(self, target, *, replacement=False):
            target = Path(target).absolute()
            require(target == target.resolve() and target.is_relative_to(output), "adapter writer escaped")
            name = str(target.relative_to(output))
            allowed = name.startswith("fixture/") or name in {"WRITER.lock", "CONFIG.json", "CONFIG.json.tmp", "COMMANDS.jsonl", "ACTIVE_USAGE.json", "ACTIVE_USAGE.json.tmp", "PROGRESS.json", "PROGRESS.json.tmp", "CAMPAIGN.json", "CAMPAIGN.json.tmp", "full-entry.json", "full-entry.json.tmp", "full-entry.log", "CONTROLS.json", "CONTROLS.json.tmp", "ADAPTERS.json", "ADAPTERS.json.tmp", "GROUPS.json", "GROUPS.json.tmp", "FAILED-adapters.json", "FAILED-adapters.json.tmp"}
            require(allowed, "unknown final adapter writer")
            return "control", name

    quota = AdapterQuota({"output": str(output), "ledger": str(work / "WRITE_USAGE.json"), "scope_sha256": sha(path), "data_bytes": 0, "control_bytes": scope["control_bytes"], "emergency_control_bytes": 8000000, "deadline_unix": scope["deadline_unix"], "reserve_bytes": 128000000})
    quota.create()
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    resource.setrlimit(resource.RLIMIT_CPU, (90, 90))
    resource.setrlimit(resource.RLIMIT_FSIZE, (8 * 1024**2, 8 * 1024**2))
    quota.install()
    commands, child = [], [None]
    original_popen = subprocess.Popen
    child_command = [scope["python_command"], "-B", "-P", str(ROOT / "tools/final_adapter_controls.py"), "--entry", str(path)]

    def spawn(command, *args, **kwargs):
        git = command in [["git", "cat-file", "--batch"], ["git", "ls-tree", "-r", "-l", "-z", "--full-tree", scope["product_commit"]]]
        require(git and sum(c[0] == "git" for c in commands) < 2 or command == child_command and child[0] is None, "adapter command/start boundary rejected")
        commands.append(command)
        process = original_popen(command, *args, **kwargs)
        if command == child_command:
            child[0] = process
        return process
    subprocess.Popen = spawn
    last = [0]
    def guard():
        lease.check()
        state = quota.read()
        require(state.get("failure") is None, "adapter write failure latched")
        if time.monotonic() - last[0] > 10:
            actual = footprint([ROOT, *scope["external_paths"]])
            storage.check_admission(actual["charged_bytes"], shutil.disk_usage(ROOT).used, 0, scope["control_bytes"] - state["control_used"] + scope["outside_control_bytes"], 128000000)
            last[0] = time.monotonic()
    campaign = None
    try:
        guard()
        campaign = Campaign(output, {"schema": "caissa-final-adapter-integration-v1", "source_commit": scope["product_commit"], "scope_sha256": sha(path)}, 90, absolute_deadline=scope["deadline_unix"], resource_guard=guard)
        fixture = output / "fixture"
        fixture.mkdir()
        def put(name, value):
            target = fixture / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
        def ref(name):
            return {"path": name, "sha256": sha(fixture / name)}
        domains = {f"G{i:02d}": {"driver": "not-integrated-final-evidence", "source_commit": scope["product_commit"], "engine_sha256": scope["engine_sha256"], "network_sha256": scope["network_sha256"], "artifacts": []} for i in range(1, 17)}
        for gate, originals in scope["staged_records"].items():
            records = {}
            for original in originals:
                target = fixture / "closed" / gate / original
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes((ROOT / original).read_bytes())
                records[original] = ref(str(target.relative_to(fixture)))
            name = "closed/" + gate + "/INDEX.json"
            put(name, {"schema": "caissa-closed-final-domain-v1", "gate": gate, "records": records})
            domains[gate].update(driver=DRIVERS[gate], final_evidence=ref(name), artifacts=[ref(name), *records.values()])
        def copied(original, name):
            target = fixture / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes((ROOT / original).read_bytes())
            return ref(name)
        learning = "results/full-model-v3-2026-10-25/"
        inputs = {"schema": "caissa-full-inputs-v1", "source_commit": scope["product_commit"], "protocol": copied("config/protocol-v4.json", "lineage/PROTOCOL.json"), "engine": copied(scope["engine"], "lineage/engine"), "network": {"artifact": copied(scope["network"], "lineage/selected.cai"), "checkpoint_sha256": scope["checkpoint_sha256"], "classical_contract": 1, "neural_weight": 10}, "dataset": {"metadata": copied("results/full-data-2026-10-25/DATASET.json", "lineage/DATASET.json")}, "learning": {"selection": copied(learning + "SELECTION.json", "lineage/SELECTION.json"), "seeds": {}}, "heldout": {}, "domains": domains}
        for seed in [17, 41, 73]:
            inputs["learning"]["seeds"][str(seed)] = {key: copied(learning + f"seed{seed}/" + name, f"lineage/seed{seed}/" + name) for key, name in [("config", "CONFIG.json"), ("checkpoints", "CHECKPOINTS.json")]}
        for name in ["config/studies.json", "config/strength-openings.json"]:
            inputs["heldout"][name] = copied(name, "lineage/" + Path(name).name)
        put("SOURCE_INPUTS.json", {"schema": "caissa-source-inputs-v2", "policy": PRODUCT, "commit": scope["product_commit"], "files": snapshot(ROOT, scope["product_commit"], PRODUCT)})
        put("FULL_INPUTS.json", inputs)
        def manifest():
            put("MANIFEST.json", {"files": {str(p.relative_to(fixture)): sha(p) for p in fixture.rglob("*") if p.is_file() and p != fixture / "MANIFEST.json"}})
        manifest()
        try:
            campaign.run("full-entry", child_command, 40, maximum_output_bytes=262144, cwd=ROOT, env=lease.environment(), pass_fds=(lease.stream.fileno(),))
        except StageFailure as failure:
            receipt = failure.record
            require(receipt["exit"] == 2 and receipt["reason"] == "nonzero-exit" and receipt["cleanup_warnings"] == [] and receipt["discarded_output_bytes"] == 0, "actual full-entry did not preserve incomplete acceptance")
        else:
            raise ValueError("partial coordinator unexpectedly exited zero")
        try:
            os.killpg(child[0].pid, 0)
        except ProcessLookupError:
            atomic(output / "GROUPS.json", [{"stage": "full-entry", "group_absent_after_reap": True}])
        else:
            raise ValueError("full-entry group survived")
        report = read(output / "full-entry.log")
        require(set(report["verified_semantic_gates"]) == {"G11", "G12"} and len(report["pending_semantic_gates"]) == 14 and report["full_acceptance"] is False, "actual full-entry gate decision differs")
        # These new cases exercise the adapter inventory, deployment and decision
        # relationships. No historical verifier main, native or browser runs.
        controls = []
        def adapter(current, gate="G12"):
            with Bundle(fixture, 30) as bundle:
                bundle.verify_manifest()
                return verify(bundle, current, ROOT, scope["product_commit"], gate)
        def rejected(name, mutate, gate="G12"):
            forged = copy.deepcopy(inputs)
            mutate(forged)
            try:
                adapter(forged, gate)
            except (ValueError, KeyError) as error:
                controls.append({"case": name, "rejected": True, "reason": str(error)})
            else:
                raise ValueError("final adapter forgery accepted: " + name)
        rejected("receipt_only_without_raw_inventory", lambda x: x["domains"]["G12"].__setitem__("artifacts", []))
        rejected("wrong_deployed_actor", lambda x: x["engine"].__setitem__("sha256", "0" * 64))
        rejected("wrong_deployed_model", lambda x: x["network"]["artifact"].__setitem__("sha256", "0" * 64))
        rejected("stale_coordinator_source", lambda x: x["domains"]["G12"].__setitem__("source_commit", "0" * 40))
        rejected("wrong_gate_driver", lambda x: x["domains"]["G12"].__setitem__("driver", DRIVERS["G11"]))
        def changed_index(name, mutate, gate="G12"):
            index_path = inputs["domains"][gate]["final_evidence"]["path"]
            original = (fixture / index_path).read_bytes()
            value = read(fixture / index_path)
            mutate(value)
            put(index_path, value)
            forged = copy.deepcopy(inputs)
            forged["domains"][gate]["final_evidence"] = ref(index_path)
            forged["domains"][gate]["artifacts"] = [ref(index_path), *value["records"].values()]
            manifest()
            try:
                try:
                    adapter(forged, gate)
                except (ValueError, KeyError) as error:
                    controls.append({"case": name, "rejected": True, "reason": str(error)})
                else:
                    raise ValueError("rehashed adapter inventory forgery accepted: " + name)
            finally:
                (fixture / index_path).write_bytes(original)
                manifest()
        changed_index("rehashed_wrong_gate_descriptor", lambda x: x.__setitem__("gate", "G11"))
        changed_index("rehashed_missing_browser_raw_body", lambda x: x["records"].pop("runs/final-served-browser-2-2026-10-29/ASSETS.json"))
        changed_index("rehashed_missing_actual_reader_stage", lambda x: x["records"].pop("runs/final-served-browser-2-2026-10-29/independent.json"))
        changed_index("rehashed_missing_closed_owner", lambda x: x["records"].pop("work/final-browser-runtime-3-2026-10-29/CLOSED.json"))
        changed_index("rehashed_missing_compiled_output", lambda x: x["records"].pop("runs/final-served-browser-2-2026-10-29/product/dist/web/app.js"))
        changed_index("rehashed_missing_original_recovery", lambda x: x["records"].pop("results/final-recovery-evidence-2026-10-29/ORIGINAL_G11.json"), "G11")
        changed_index("rehashed_missing_recovery_raw_session", lambda x: x["records"].pop("runs/final-current-recovery-2026-10-29/native/session-01.json"), "G11")
        def changed_record(name, original_name, mutate):
            index_path = inputs["domains"]["G12"]["final_evidence"]["path"]
            index_original = (fixture / index_path).read_bytes()
            index = read(fixture / index_path)
            target = index["records"][original_name]["path"]
            raw_original = (fixture / target).read_bytes()
            value = read(fixture / target)
            mutate(value)
            put(target, value)
            index["records"][original_name] = ref(target)
            put(index_path, index)
            forged = copy.deepcopy(inputs)
            forged["domains"]["G12"]["final_evidence"] = ref(index_path)
            forged["domains"]["G12"]["artifacts"] = [ref(index_path), *index["records"].values()]
            manifest()
            try:
                try:
                    adapter(forged)
                except (ValueError, KeyError) as error:
                    controls.append({"case": name, "rejected": True, "reason": str(error)})
                else:
                    raise ValueError("rehashed actual-execution forgery accepted: " + name)
            finally:
                (fixture / target).write_bytes(raw_original)
                (fixture / index_path).write_bytes(index_original)
                manifest()
        changed_record("rehashed_failed_actual_owner", "work/final-browser-runtime-3-2026-10-29/CLOSED.json", lambda x: x.__setitem__("owner_exit", 1))
        changed_record("rehashed_open_write_ledger", "work/final-browser-runtime-3-2026-10-29/WRITE_USAGE.json", lambda x: x.__setitem__("closed", False))
        changed_record("rehashed_failed_actual_reader_exit", "runs/final-served-browser-2-2026-10-29/independent.json", lambda x: x.__setitem__("exit", 1))
        with Bundle(fixture, 30) as bundle:
            bundle.verify_manifest()
            negative_review = {"full_acceptance": False, "pending_semantic_gates": {"G11": "pending", "G12": "pending", "G15": "original compiler closure missing"}, "failed_semantic_gates": {"G08": {"status": "failed_original_neural_gain"}}}
            integrate(bundle, inputs, ROOT, scope["product_commit"], negative_review)
            require(negative_review["failed_semantic_gates"]["G08"]["status"] == "failed_original_neural_gain" and negative_review["pending_semantic_gates"] == {"G15": "original compiler closure missing"} and negative_review["full_acceptance"] is False, "integration dropped failed or unavailable gate")
            controls.append({"case": "preserves_failed_and_missing_gates", "passed": True})
        atomic(output / "CONTROLS.json", controls)
        atomic(output / "ADAPTERS.json", {"status": "passed_final_G11_G12_adapter_integration", "product_source_commit": scope["product_commit"], "scope_sha256": sha(path), "full_entry_actual_exit": receipt["exit"], "verified_final_gates": ["G11", "G12"], "remaining_pending_gates": sorted(report["pending_semantic_gates"]), "controls": len(controls), "original_source_inventory_policy_unchanged": True, "explicit_cjs_source_bound": True, "native_starts": 0, "browser_starts": 0, "closed_semantic_samples_reexecuted": 0, "full_R12_complete": False, "full_acceptance": False})
        campaign.close("passed-final-adapter-integration-component")
    except BaseException as error:
        if campaign is not None:
            atomic(output / "FAILED-adapters.json", {"reason": str(error), "full_acceptance": False})
            campaign.close("failed", {"reason": str(error)})
        raise
    finally:
        subprocess.Popen = original_popen
        if campaign is not None:
            atomic(output / "ACTIVE_USAGE.json", {"closed": True, "active_seconds": time.monotonic() - campaign.start})
        quota.uninstall()
        quota.update(lambda state: state.update(closed=True))
        lease.close()


if __name__ == "__main__":
    if sys.argv[1] == "--entry":
        entry(sys.argv[2])
    else:
        main(sys.argv[1])
