"""One finite read-only lineage join and new relationship controls."""

import ast
import copy
import fcntl
import hashlib
import json
import os
from pathlib import Path
import resource
import signal
import stat
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from verification.final_lineage import BOUNDARY, G07, LEARNING, READERS, TRAINING, ordinary_ast, require, validate


def main(path):
    start = time.monotonic()
    path = Path(path).resolve()
    scope = json.loads(path.read_text())
    output = path.parent
    require(scope["status"] == "admitted" and time.time() < scope["deadline_unix"] <= scope["parent_deadline_unix"] and not (output / "STARTED.json").exists(), "one fresh finite lineage scope required")
    os.umask(0o077)
    lease = (ROOT / "runs/TIMED_STRENGTH.lock").open("r+")
    fcntl.flock(lease, fcntl.LOCK_EX | fcntl.LOCK_NB)
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    resource.setrlimit(resource.RLIMIT_CPU, (20, 20))
    resource.setrlimit(resource.RLIMIT_FSIZE, (512000, 512000))
    def stop(*_):
        raise TimeoutError("finite lineage deadline exhausted")
    signal.signal(signal.SIGALRM, stop)
    signal.setitimer(signal.ITIMER_REAL, min(20, scope["deadline_unix"] - time.time()))
    allowed = {output / n for n in ("STARTED.json", "LINEAGE.json", "CONTROLS.json", "AVAILABILITY.json", "METADATA_USAGE.json")}
    def audit(event, args):
        if event.startswith("socket.") or event in {"subprocess.Popen", "os.system", "os.posix_spawn", "os.exec", "os.link", "os.symlink", "os.remove", "os.rename", "os.mkdir"}:
            raise ValueError("lineage join admits no child, network or filesystem mutation")
        if event == "open":
            name, mode, flags = args
            writing = isinstance(mode, str) and any(c in mode for c in "wax+") or isinstance(flags, int) and flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND)
            if writing:
                require(isinstance(name, (str, bytes)) and Path(name).absolute() in allowed and Path(name).absolute() == Path(name).resolve() and mode == "x", "lineage write escaped immutable exact outputs")
    sys.addaudithook(audit)
    used = [scope["outside_control_bytes"]]
    def put(name, value):
        raw = json.dumps(value, indent=2, sort_keys=True) + "\n"
        used[0] += len(raw.encode())
        require(used[0] <= scope["control_bytes"] + scope["outside_control_bytes"], "lineage shared output allowance exhausted")
        with (output / name).open("x") as stream:
            stream.write(raw)
    put("STARTED.json", {"unix": time.time()})
    require(str(Path(sys.executable).resolve()) == scope["interpreter"] and hashlib.sha256(Path(sys.executable).read_bytes()).hexdigest() == scope["interpreter_sha256"], "lineage Python identity differs")
    raw = {}
    for name, expected in scope["input_bindings"].items():
        p = ROOT / name
        require(p.resolve() == p and stat.S_ISREG(p.stat().st_mode) and p.stat().st_size <= 16 * 1024**2, "lineage input is nonregular, escaped or oversized")
        value = p.read_bytes()
        require(hashlib.sha256(value).hexdigest() == expected, "lineage input differs: " + name)
        raw[name] = value
    d = {name: json.loads(raw[name]) for name in scope["documents"]}
    b = d[BOUNDARY]
    availability = {
        "original_checkpoint_paths": {f"runs/searched-full-model-v3/seed{seed}/checkpoints/step-{step:08d}.pt": (ROOT / f"runs/searched-full-model-v3/seed{seed}/checkpoints/step-{step:08d}.pt").exists() for seed in (17, 41, 73) for step in range(250, 20001, 250)},
        "original_array_paths": {"data/searched-full-v3-prepared/" + n: (ROOT / "data/searched-full-v3-prepared" / n).exists() for n in d["results/full-data-2026-10-25/DATASET.json"]["files"]},
        "original_audit_catalog_paths": {n: (ROOT / n).exists() for n in scope["unavailable_catalogs"]},
        "selected_alternate": {"path": scope["checkpoint"], "sha256": scope["input_bindings"][scope["checkpoint"]], "bytes": len(raw[scope["checkpoint"]])},
        "retained_validation_slice_sha256": {n: scope["input_bindings"]["results/precision-v4-inputs/validation/" + n] for n in d["results/precision-v4-inputs/validation/SLICE.json"]["files"]},
        "full_raw_reproduction_available": False,
        "availability_scope": "Exact original six arrays, 240 scheduled checkpoint paths and three original input catalogs. No claim to enumerate retired per-game corpus leaves from unavailable catalogs.",
    }
    source_equal, source_details = {}, {}
    for name in ("training/train.py", "training/prepare.py"):
        current, removed = ordinary_ast(raw[name], name)
        historical = raw[scope["historical_sources"][name]]
        require(hashlib.sha256(historical).hexdigest() == d[G07 + "SOURCE_INPUTS.json"]["files"][name], "archived original training source differs")
        source_equal[name] = current == ast.dump(ast.parse(historical), include_attributes=False)
        source_details[name] = {"historical_sha256": hashlib.sha256(historical).hexdigest(), "current_sha256": scope["input_bindings"][name], "ordinary_AST_equal": source_equal[name], "excluded_optional_branches": removed}
    commands = [json.loads(row) for row in raw[LEARNING + "COMMANDS.jsonl"].decode().splitlines()]
    training = [row["command"] for row in commands if row.get("event") == "stage-started" and "training.train" in row.get("command", [])]
    require(len(training) == 3, "original three training invocations missing")
    require([int(command[command.index("--seed") + 1]) for command in training] == [17, 41, 73] and all(command[command.index("training.train") + 1] == str(ROOT / "data/searched-full-v3-prepared") and command[command.index("--steps") + 1] == "20000" and command[command.index("--checkpoint-every") + 1] == "250" for command in training), "original training data path or fixed schedule differs")
    e = {"documents": d, "identities": scope["input_bindings"], "availability": availability, "teacher_sha256": d["results/full-data-2026-10-25/DATASET.json"]["corpus_config"]["engine_sha256"], "retained_engine_sha256": scope["input_bindings"][scope["engine"]], "retained_network_sha256": scope["input_bindings"][scope["network"]], "retained_checkpoint_sha256": scope["input_bindings"][scope["checkpoint"]], "network_header_checkpoint": raw[scope["network"]][40:104].decode("ascii"), "network_header_version": int.from_bytes(raw[scope["network"]][8:12], "little"), "native_hashes": {n: scope["input_bindings"][n] for n in b["native_source_sha256"]}, "native_modes": {n: "100755" if (ROOT / n).stat().st_mode & 0o111 else "100644" for n in b["native_source_modes"]}, "current_source_sha256": {n: scope["input_bindings"][n] for n in READERS + TRAINING}, "ordinary_source_AST_equal": source_equal, "historical_training_used_resume": any("--resume" in command or "--recovery-barrier" in command for command in training), "new_training": False, "new_selection": False, "full_acceptance": False}
    result = validate(e)
    controls = []
    for name, mutate in [
        ("missing_real_independent_stage", lambda x: x["documents"].pop(G07 + "data/execution/independent.json")),
        ("failed_real_learning_exit", lambda x: x["documents"][G07 + "execution/learning.json"].update(exit=1)),
        ("changed_actual_stage_log_hash", lambda x: x["documents"][G07 + "execution/data.json"].update(log_sha256="0" * 64)),
        ("historical_gate_promoted_from_component", lambda x: x["documents"][G07 + "G07.json"].update(full_gate=False)),
        ("changed_original_selected_step", lambda x: x["documents"][LEARNING + "SELECTION.json"]["selected"].update(step=3000)),
        ("incomplete_all_checkpoint_audit", lambda x: x["documents"][G07 + "learning/LEARNING.json"].update(all_checkpoints_independently_evaluated=239)),
        ("wrong_retained_float_bytes", lambda x: x.update(retained_checkpoint_sha256="0" * 64)),
        ("old_export_substituted_as_final", lambda x: x.update(retained_network_sha256=x["documents"][LEARNING + "MODEL_CAMPAIGN.json"]["network_sha256"])),
        ("final_actor_substituted_as_old_teacher", lambda x: x.update(teacher_sha256=x["retained_engine_sha256"])),
        ("changed_independent_reader_source", lambda x: x["current_source_sha256"].update({"verification/learning.py": "0" * 64})),
        ("changed_final_native_mode", lambda x: x["native_modes"].update({next(iter(x["native_modes"])): "100755"})),
        ("invented_retired_checkpoint_availability", lambda x: x["availability"]["original_checkpoint_paths"].update({next(iter(x["availability"]["original_checkpoint_paths"])): True})),
        ("validation_slice_promoted_to_full_reproduction", lambda x: x["availability"].update(full_raw_reproduction_available=True)),
        ("old_numerical_failures_erased", lambda x: x["documents"][LEARNING + "MODEL_CAMPAIGN.json"].update(failed_domains=[])),
        ("full_acceptance_promoted_from_lineage", lambda x: x.update(full_acceptance=True)),
    ]:
        forged = copy.deepcopy(e)
        mutate(forged)
        try:
            validate(forged)
        except (ValueError, KeyError) as error:
            controls.append({"case": name, "rejected": True, "reason": str(error)})
        else:
            raise ValueError("new lineage forgery accepted: " + name)
    for name in ("training/train.py", "training/prepare.py"):
        forged = raw[name].decode() + "\nUNRELATED_LINEAGE_CHANGE = True\n"
        changed, _ = ordinary_ast(forged, name)
        require(changed != ast.dump(ast.parse(raw[scope["historical_sources"][name]]), include_attributes=False), "ordinary-path source comparison hid an unrelated edit")
        controls.append({"case": name + " unrelated_source_edit", "rejected": True})
    result.update(product_source_commit=scope["product_commit"], source_relationships=source_details, original_training_invocations=len(training), negative_controls=len(controls), elapsed_seconds=time.monotonic() - start, native_starts=0, games=0, closed_semantic_sample_replays=0, full_bundle_coordinator_executed=False)
    put("AVAILABILITY.json", availability)
    put("CONTROLS.json", controls)
    put("LINEAGE.json", result)
    put("METADATA_USAGE.json", {"closed": True, "failure": None, "charged_before_ledger_bytes": used[0], "control_limit_bytes": scope["control_bytes"], "outside_control_prepaid_bytes": scope["outside_control_bytes"], "native_starts": 0, "child_starts": 0, "scope_sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
    print(json.dumps({"status": result["status"], "controls": len(controls), "elapsed_seconds": result["elapsed_seconds"], "full_acceptance": False}))


if __name__ == "__main__":
    main(sys.argv[1])
