"""One finite G14 provenance join and genuinely new relationship controls."""

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
from verification.final_semantic_join import FAMILIES, READERS, branch, require, validate


def main(path):
    started = time.monotonic()
    path = Path(path).resolve()
    scope = json.loads(path.read_text())
    output = path.parent
    require(scope["status"] == "admitted" and time.time() < scope["deadline_unix"] <= scope["parent_deadline_unix"] and not (output / "STARTED.json").exists(), "one fresh G14 relationship invocation required")
    os.umask(0o077)
    lease = (ROOT / "runs/TIMED_STRENGTH.lock").open("r+")
    fcntl.flock(lease, fcntl.LOCK_EX | fcntl.LOCK_NB)
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    resource.setrlimit(resource.RLIMIT_CPU, (20, 20))
    resource.setrlimit(resource.RLIMIT_FSIZE, (512000, 512000))
    def stop(*_):
        raise TimeoutError("G14 relationship deadline exhausted")
    signal.signal(signal.SIGALRM, stop)
    signal.setitimer(signal.ITIMER_REAL, min(20, scope["deadline_unix"] - time.time()))
    allowed = {output / n for n in ["STARTED.json", "SEMANTIC_JOIN.json", "CONTROLS.json", "METADATA_USAGE.json"]}
    def audit(event, args):
        if event.startswith("socket.") or event in {"subprocess.Popen", "os.system", "os.posix_spawn", "os.exec", "os.link", "os.symlink", "os.remove", "os.rename", "os.mkdir"}:
            raise ValueError("G14 relationship join prohibits process/network/mutation")
        if event == "open":
            name, mode, flags = args
            writing = isinstance(mode, str) and any(c in mode for c in "wax+") or isinstance(flags, int) and flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND)
            if writing:
                require(isinstance(name, str) and Path(name).absolute() == Path(name).resolve() and Path(name).absolute() in allowed and mode == "x", "G14 relationship output escaped immutable inventory")
    sys.addaudithook(audit)
    def put(name, value):
        raw = json.dumps(value, indent=2, sort_keys=True) + "\n"
        require(len(raw.encode()) <= 512000, "G14 compact relationship file exceeded")
        with (output / name).open("x") as stream:
            stream.write(raw)
    put("STARTED.json", {"unix": time.time()})
    require(str(Path(sys.executable).resolve()) == scope["interpreter"] and hashlib.sha256(Path(sys.executable).read_bytes()).hexdigest() == scope["interpreter_sha256"], "G14 relationship interpreter differs")
    values = {}
    for name, digest in scope["input_bindings"].items():
        p = ROOT / name
        require(p.resolve() == p and stat.S_ISREG(p.stat().st_mode) and p.stat().st_size <= 16 * 1024**2, "G14 relationship input escaped or exceeded")
        raw = p.read_bytes()
        require(hashlib.sha256(raw).hexdigest() == digest, "G14 pinned relationship input differs: " + name)
        values[name] = raw
    doc = lambda n: json.loads(values[n])
    archive = scope["archive_work"] + "/"
    current = "runs/final-lineage-adapter-2026-10-29/"
    prior_scope = doc("work/final-lineage-adapter-1-2026-10-29/SCOPE.json")
    boundary = doc("results/final-core-runtime-join-2026-10-28/BOUNDARY.json")
    current_source = values["verification/full_bundle.py"]
    historical_source = values[archive + "ORIGINAL_FULL_BUNDLE.py"]
    e = {"archive": doc(archive + "RESULT.json"), "archive_scope_sha256": scope["input_bindings"][archive + "SCOPE.json"], "owner": doc(archive + "CLOSED.json"), "transport": doc(archive + "TRANSPORT.json"), "ledger": doc(archive + "METADATA_USAGE.json"), "original": doc(archive + "records/ORIGINAL_G14.json"), "config": doc(archive + "raw/CONFIG.json"), "raw_manifest": doc(archive + "raw/MANIFEST.json"), "raw_manifest_sha256": scope["input_bindings"][archive + "raw/MANIFEST.json"], "raw_pins": {n: hashlib.sha256(values[archive + "raw/" + n]).hexdigest() for n in doc(archive + "RESULT.json")["raw_positive_sha256"]}, "original_source_inventory": doc(archive + "raw/SOURCE_INPUTS.json"), "rejection_manifests": doc(archive + "records/REJECTION_MANIFESTS.json"), "cases": {n: doc(archive + "records/" + n + "-RESULT.json") for n in ["positive-full-entry", "missing-replay-output", *FAMILIES, "undeclared-raw-artifact"]}, "boundary": boundary, "current_native_sha256": {n: hashlib.sha256(values[n]).hexdigest() for n in boundary["native_source_sha256"]}, "current_native_modes": {n: "100755" if (ROOT / n).stat().st_mode & 0o111 else "100644" for n in boundary["native_source_modes"]}, "reader_source_sha256": {n: hashlib.sha256(values[n]).hexdigest() for n in READERS}, "current_original_reader_hash": hashlib.sha256(values["verification/semantic_audit.py"]).hexdigest(), "G14_legacy_branch_AST_equal": branch(current_source, "G14") == branch(historical_source, "G14"), "G11_strict_branch_AST_equal": branch(current_source, "G11") == branch(historical_source, "G11"), "accepted_eleven_domain_report": doc(current + "full-entry.log"), "eleven_domain_stage": doc(current + "full-entry.json"), "eleven_domain_log_sha256": scope["input_bindings"][current + "full-entry.log"], "prior_final_adapter_sources_match": all(hashlib.sha256(values[n]).hexdigest() == prior_scope["source_bindings"][n] for n in ["verification/final_evidence_bundle.py", "verification/final_core_bundle.py"])}
    result = validate(e)
    controls = []
    for name, mutate in [
        ("wrong_archive_digest", lambda x: x["archive"].update(archive_sha256="0" * 64)),
        ("failed_archive_owner", lambda x: x["owner"].update(owner_exit=1)),
        ("unreaped_transport_group", lambda x: x["transport"].update(owned_group_absent_after_reap=False)),
        ("open_metadata_ledger", lambda x: x["ledger"].update(closed=False)),
        ("different_saved_engine", lambda x: x["original"].update(engine_sha256="0" * 64)),
        ("incomplete_positive_witnesses", lambda x: x["original"]["positive_witnesses"].update(draw_histories=3)),
        ("missing_recorded_rejection", lambda x: x["rejection_manifests"].pop()),
        ("nonsemantic_original_rejection", lambda x: x["original"]["rehashed_semantic_rejections"][0].update(rejection="only wrong hash")),
        ("missing_actual_full_entry_case", lambda x: x["cases"].pop("undeclared-raw-artifact")),
        ("promoted_original_entry_exit", lambda x: x["cases"]["positive-full-entry"].update(exit=0)),
        ("changed_current_native_mode", lambda x: x["current_native_modes"].update({next(iter(x["current_native_modes"])): "100755"})),
        ("changed_independent_reader", lambda x: x["reader_source_sha256"].update({READERS[0]: "0" * 64})),
        ("weakened_strict_G11_branch", lambda x: x.update(G11_strict_branch_AST_equal=False)),
        ("changed_legacy_G14_branch", lambda x: x.update(G14_legacy_branch_AST_equal=False)),
        ("forged_previous_all_domain_acceptance", lambda x: x["accepted_eleven_domain_report"].update(full_acceptance=True)),
        ("failed_prior_full_entry", lambda x: x["eleven_domain_stage"].update(exit=1)),
    ]:
        forged = copy.deepcopy(e)
        mutate(forged)
        try:
            validate(forged)
        except (ValueError, KeyError) as error:
            controls.append({"case": name, "rejected": True, "reason": str(error)})
        else:
            raise ValueError("new G14 relationship forgery accepted: " + name)
    result.update(product_source_commit=scope["product_commit"], original_G14_result_sha256=scope["input_bindings"][archive + "records/ORIGINAL_G14.json"], original_raw_manifest_sha256=e["raw_manifest_sha256"], archive_scope_sha256=e["archive_scope_sha256"], negative_controls=len(controls), elapsed_seconds=time.monotonic() - started)
    put("CONTROLS.json", controls)
    put("SEMANTIC_JOIN.json", result)
    put("METADATA_USAGE.json", {"closed": True, "failure": None, "scope_sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "native_starts": 0, "child_starts": 0})
    print(json.dumps({"status": result["status"], "controls": len(controls), "elapsed_seconds": result["elapsed_seconds"], "full_acceptance": False}))


if __name__ == "__main__":
    main(sys.argv[1])
