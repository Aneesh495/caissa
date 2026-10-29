"""Join accepted core runtime evidence without executing closed samples again."""

import copy
import fcntl
import hashlib
import json
import os
from pathlib import Path
import resource
import signal
import stat
import subprocess
import sys
import time
import zipfile


DOMAINS = {
    "G01": ("rules", "RULES.json", "independent/", "verification/rules.py"),
    "G02": ("restoration", "RESTORATION.json", "independent/", "verification/restoration.py"),
    "G03": ("draw", "DRAW_HISTORY.json", "independent/", "verification/draw_history.py"),
    "G04": ("protocol", "PROTOCOL_REPLAY.json", "", "verification/protocol.py"),
    "G06": ("numerical", "NUMERICAL_REPLAY.json", "", "verification/numerical.py"),
}


def require(value, reason):
    if not value:
        raise ValueError(reason)


def equal(a, b):
    if type(a) is not type(b):
        return False
    if isinstance(a, dict):
        return a.keys() == b.keys() and all(equal(a[k], b[k]) for k in a)
    if isinstance(a, list):
        return len(a) == len(b) and all(equal(x, y) for x, y in zip(a, b))
    return a == b


def validate(rows, boundary):
    require(set(rows) == {f"G{i:02}" for i in range(1, 7)}, "missing or additional core domain")
    for gate, row in rows.items():
        r = row["reader"]
        require(r["status"] == "passed" and r["full_acceptance"] is False, gate + " reader did not pass independently")
        require(r["engine_sha256"] == boundary["engine_sha256"], gate + " saved actor differs")
        if "network_sha256" in r:
            require(r["network_sha256"] == boundary["network_sha256"], gate + " model differs")
        if "checkpoint_sha256" in r:
            require(r["checkpoint_sha256"] == boundary["checkpoint_sha256"], gate + " checkpoint differs")
        require(equal(r, row["published"]), gate + " published reader differs from actual artifact")
        require(r.get("profile_sha256", row["profile_sha256"]) == row["profile_sha256"], gate + " profile differs")
        require(row["closed"] is True and row["owner_exit"] == 0 and type(row["owner_exit"]) is int, gate + " owner not cleanly closed")
        for stage in row["stages"]:
            require(type(stage["exit"]) is int and stage["exit"] == 0 and stage["reason"] == "completed" and stage["cleanup_warnings"] == [], gate + " stage failed or child cleanup incomplete")
    r = {gate: row["reader"] for gate, row in rows.items()}
    require(type(r["G01"]["positions"]) is int and r["G01"]["positions"] == 100000 and r["G01"]["unique"] == 96589, "G01 full position schedule differs")
    require(len(r["G01"]["perft"]) == 20 and all(x["native"] == x["oracle"] for x in r["G01"]["perft"]), "G01 perft differs")
    require(r["G02"]["pairs"] == 1000000 and type(r["G02"]["pairs"]) is int and r["G02"]["requests"] == 3040911 and r["G02"]["independent_full_state_checks"] == 1040911 and r["G02"]["records"] == 1018090 and r["G02"]["native_exit"] == 0, "G02 incomplete full state/native replay")
    require(r["G03"]["histories"] == 92 and r["G03"]["observations"] == 2195 and all(r["G03"]["equal_board_witnesses"].values()) and r["G03"]["native_exit"] == 0, "G03 history schedule differs")
    require(r["G04"]["completed"] == 10000 and r["G04"]["ponder_completed"] == 100 and r["G04"]["bestmoves"] == 10100 and r["G04"]["threads_observed"] == [1, 2, 4, 8] and r["G04"]["stop_ms"]["p99"] < 50, "G04 protocol schedule or stop endpoint differs")
    require(r["G05"]["observations"] == 3080 and r["G05"]["categories"] == {"table": 1344, "clear": 868, "exact": 752, "regression": 4, "ablation": 112} and r["G05"]["oracle_nodes"] == 256430 and r["G05"]["native_exit"] == 0, "G05 accepted search schedule differs")
    require(r["G06"]["probes"] == 100000 and r["G06"]["unique_fens"] == 97075 and r["G06"]["maximum_error_cp"] == 32.0 and r["G06"]["float64_quantized_cp"]["max"] < 32 and r["G06"]["raw_float64_quantized_cp"]["max"] < 32 and r["G06"]["native_replay"]["exit"] == 0 and r["G06"]["test_arrays_opened"] is False, "G06 numerical endpoint differs")


def main(scope_path):
    started = time.monotonic()
    scope_path = Path(scope_path).resolve()
    scope = json.loads(scope_path.read_text())
    root, output = Path(scope["root"]), scope_path.parent
    require(scope["status"] == "admitted" and time.time() < scope["deadline_unix"], "fresh finite scope required")
    require(not (output / "STARTED.json").exists(), "one invocation only")
    lease = (root / "runs/TIMED_STRENGTH.lock").open("r+")
    fcntl.flock(lease.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    resource.setrlimit(resource.RLIMIT_FSIZE, (512000, 512000))
    resource.setrlimit(resource.RLIMIT_CPU, (30, 30))

    def stop(*_):
        raise TimeoutError("core evidence join deadline exhausted")

    signal.signal(signal.SIGALRM, stop)
    signal.setitimer(signal.ITIMER_REAL, min(scope["maximum_active_seconds"], scope["deadline_unix"] - time.time()))

    def audit(event, args):
        if event.startswith("socket.") or event in {"os.system", "os.posix_spawn", "os.exec"}:
            raise RuntimeError("no network or actors in core join")
        if event == "subprocess.Popen":
            executable, argv = args[:2]
            require(Path(executable).name == "git" and argv[1] in {"ls-tree", "cat-file", "rev-parse", "ls-files", "show"}, "only read-only Git operations admitted")
        if event == "open":
            name, mode, flags = args
            writing = (isinstance(mode, str) and any(x in mode for x in "wax+")) or (isinstance(flags, int) and flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND))
            if writing:
                if isinstance(name, int):
                    require(stat.S_ISFIFO(os.fstat(name).st_mode), "only Git pipes admitted by descriptor")
                else:
                    require(Path(name).resolve().is_relative_to(output), "core join write escaped its output")

    sys.addaudithook(audit)
    (output / "STARTED.json").write_text(json.dumps({"started_unix": time.time()}) + "\n")
    sys.path.insert(0, str(root))
    from verification.bundle import strict_json
    from verification.runtime_binding import bounded, inspect

    require(str(Path(sys.executable).resolve()) == scope["interpreter"], "interpreter differs")
    require(hashlib.sha256(Path(sys.executable).read_bytes()).hexdigest() == scope["interpreter_sha256"], "interpreter bytes differ")

    def digest(name):
        require(name in scope["input_bindings"], "unbound input: " + name)
        path = root / name
        if path.lstat().st_size == 0:
            require(path.is_file() and not path.is_symlink(), "empty input is not a regular file")
            raw, sha = b"", hashlib.sha256(b"").hexdigest()
        else:
            raw, sha = bounded(path, 32 * 1024**2)
        require(sha == scope["input_bindings"][name], "pinned input differs: " + name)
        return raw

    def doc(name):
        return strict_json(digest(name))

    for name in scope["input_bindings"]:
        digest(name)
    boundary = inspect(root, scope["product_commit"], root / "config/protocol-v4.json", scope["input_bindings"]["config/protocol-v4.json"], root / scope["engine"], root / scope["network"], root / scope["learning_receipt"])
    require(boundary["matched_native_files"] == 69, "native inventory differs")
    require(hashlib.sha256(digest(scope["checkpoint"])).hexdigest() == boundary["checkpoint_sha256"], "retained floating checkpoint differs")
    rows = {}
    for gate, (kind, report, prefix, reader) in DOMAINS.items():
        run = f"runs/final-saved-actor-{kind}-2026-10-28"
        work = f"work/final-{kind}-runtime-1-2026-10-28"
        public = f"results/final-saved-actor-{kind}-2026-10-28"
        s, closure = doc(work + "/SCOPE.json"), doc(work + "/CLOSED.json")
        execution = doc(public + "/EXECUTION.json")
        actual, published = doc(run + "/" + prefix + report), doc(public + "/" + report)
        require(closure["scope_sha256"] == scope["input_bindings"][work + "/SCOPE.json"] and closure["independent_closure_error"] is None, gate + " closure binding differs")
        require(s["product_commit"] == execution["source_commit"] and s["engine_sha256"] == boundary["engine_sha256"], gate + " execution source or actor differs")
        require(doc(run + "/ACTIVE_USAGE.json")["closed"] is True, gate + " active ledger open")
        writes = doc(work + "/WRITE_USAGE.json")
        require(writes["closed"] is True and writes.get("failure") is None and writes["native_starts"] == s["maximum_native_actor_starts"], gate + " write/native ledger incomplete")
        source = subprocess.run(["git", "show", s["product_commit"] + ":" + reader], cwd=root, capture_output=True, check=True, timeout=5).stdout
        require(hashlib.sha256(source).hexdigest() == s["source_bindings"][reader], gate + " independent reader source differs from pinned execution")
        stages = [doc(run + "/" + name + ".json") for name in ["produce", "independent"]]
        for name, stage in zip(["produce", "independent"], stages):
            require(hashlib.sha256(digest(run + "/" + name + ".log")).hexdigest() == stage["log_sha256"], gate + " actual stage log differs")
            require(all(equal(stage[k], v) for k, v in execution["stages"][name].items()), gate + " public stage receipt differs")
        if gate == "G01":
            for expected in execution["perft_stages"]:
                actual_stage = doc(run + "/independent/perft-" + expected["id"] + ".json")
                require(all(equal(actual_stage[k], v) for k, v in expected.items() if k != "id"), "G01 perft stage differs")
                stages.append(actual_stage)
        manifest = doc(public + "/MANIFEST.json")
        require(all(scope["input_bindings"][public + "/" + n] == h for n, h in manifest.items()), gate + " public manifest differs")
        rows[gate] = {"reader": actual, "published": published, "profile_sha256": s.get("profile_sha256"), "closed": closure["closed"], "owner_exit": closure["owner_exit"], "stages": stages, "source_commit": s["product_commit"], "reader_source_sha256": s["source_bindings"][reader]}

    search = "results/search-semantics-2026-10-25"
    index, manifest = doc(search + "/RAW_INDEX.json"), doc(search + "/MANIFEST.json")["files"]
    require(hashlib.sha256(digest(search + "/RAW.zip")).hexdigest() == manifest["RAW.zip"], "G05 archive differs")
    with zipfile.ZipFile(root / search / "RAW.zip") as archive:
        def archived(name):
            raw = archive.read(name)
            require(hashlib.sha256(raw).hexdigest() == index[name], "G05 original archive member differs")
            return strict_json(raw)
        old = "semantic-attempt-001/"
        reader = archived(old + "independent/SEARCH_SEMANTICS.json")
        campaign = archived(old + "CAMPAIGN.json")
        stage = archived(old + "independent.json")
        producer = archived(old + "producer.json")
    require(reader["source_commit"] == boundary["compiled_source_commit"], "G05 compiled source differs")
    require(len(campaign["details"]["controls"]) == 12 and all(c["actual_exit"] == 1 for c in campaign["details"]["controls"]), "G05 original rejection controls differ")
    rows["G05"] = {"reader": reader, "published": doc(search + "/SEARCH_SEMANTICS.json"), "profile_sha256": hashlib.sha256(digest(search + "/PROFILE.json")).hexdigest(), "closed": campaign["status"] == "passed", "owner_exit": 0 if campaign["status"] == "passed" else 1, "stages": [producer, stage], "source_commit": reader["source_commit"]}
    validate(rows, boundary)
    controls = []

    def reject(name, mutate):
        changed = copy.deepcopy(rows)
        mutate(changed)
        try:
            validate(changed, boundary)
        except ValueError as error:
            controls.append({"case": name, "status": "rejected", "reason": str(error)})
        else:
            raise ValueError("forged core evidence accepted: " + name)

    def rehashed(gate, field, value):
        def mutate(changed):
            changed[gate]["reader"][field] = value
            changed[gate]["published"][field] = value
        return mutate

    reject("missing-domain", lambda x: x.pop("G02"))
    reject("different-actor-rehashed", rehashed("G02", "engine_sha256", "0" * 64))
    reject("different-model-rehashed", rehashed("G06", "network_sha256", "0" * 64))
    reject("different-checkpoint-rehashed", rehashed("G06", "checkpoint_sha256", "0" * 64))
    reject("different-profile-rehashed", rehashed("G03", "profile_sha256", "0" * 64))
    reject("incomplete-million-pair-rehashed", rehashed("G02", "pairs", 999999))
    reject("boolean-count-rehashed", rehashed("G02", "pairs", True))
    reject("incomplete-protocol-rehashed", rehashed("G04", "ponder_completed", 99))
    reject("failed-reader-rehashed", rehashed("G01", "status", "failed"))
    reject("forged-full-acceptance-rehashed", rehashed("G05", "full_acceptance", True))
    reject("open-owner", lambda x: x["G03"].update(closed=False))
    reject("failed-stage", lambda x: x["G06"]["stages"][1].update(exit=1))
    reject("child-cleanup-failure", lambda x: x["G04"]["stages"][0].update(cleanup_warnings=["unreaped child"]))
    reject("published-result-differs", lambda x: x["G01"]["published"].update(positions=99999))
    result = {"status": "passed_core_runtime_evidence_join", "product_source_commit": scope["product_commit"], "engine_sha256": boundary["engine_sha256"], "network_sha256": boundary["network_sha256"], "matched_native_files": 69, "domains": {g: {"status": "joined_accepted_runtime", "source_commit": r["source_commit"], "profile_sha256": r["profile_sha256"], "reader_sha256": hashlib.sha256(json.dumps(r["reader"], sort_keys=True).encode()).hexdigest()} for g, r in sorted(rows.items())}, "negative_controls": controls, "elapsed_seconds": time.monotonic() - started, "native_starts": 0, "games": 0, "semantic_sample_reruns": 0, "original_compiler_runtime_closure_established": False, "full_bundle_coordinator_executed": False, "full_gate": False, "full_acceptance": False}
    (output / "BOUNDARY.json").write_text(json.dumps(boundary, indent=2) + "\n")
    (output / "CORE_RUNTIME_JOIN.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({"status": result["status"], "domains": list(result["domains"]), "controls": len(controls), "elapsed_seconds": result["elapsed_seconds"], "full_acceptance": False}))


if __name__ == "__main__":
    main(sys.argv[1])
