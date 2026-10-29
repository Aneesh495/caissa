"""Inspect retained source-matched TSan archives and join existing thread evidence."""

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


def require(value, reason):
    if not value:
        raise ValueError(reason)


def main(scope_path):
    started = time.monotonic()
    scope_path = Path(scope_path).resolve()
    scope = json.loads(scope_path.read_text())
    root, output = Path(scope["root"]), scope_path.parent
    require(scope["status"] == "admitted" and time.time() < scope["deadline_unix"] and not (output / "STARTED.json").exists(), "one fresh bounded inspection required")
    lease = (root / "runs/TIMED_STRENGTH.lock").open("r+")
    fcntl.flock(lease.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    resource.setrlimit(resource.RLIMIT_FSIZE, (32 * 1024**2, 32 * 1024**2))
    resource.setrlimit(resource.RLIMIT_CPU, (90, 90))

    def stop(*_):
        raise TimeoutError("thread evidence inspection deadline exhausted")

    signal.signal(signal.SIGALRM, stop)
    signal.setitimer(signal.ITIMER_REAL, min(180, scope["deadline_unix"] - time.time()))
    admitted = [["gh", "api", f"repos/Aneesh495/caissa/actions/artifacts/{a['id']}/zip"] for a in scope["artifacts"]]
    launched = []

    def audit(event, args):
        if event.startswith("socket.") or event in {"os.system", "os.posix_spawn", "os.exec"}:
            raise RuntimeError("only identified GitHub artifact fetches admitted")
        if event == "subprocess.Popen":
            argv = args[1]
            require(argv in admitted and argv not in launched, "only one fetch per pinned existing artifact")
            launched.append(argv)
        if event == "open":
            name, mode, flags = args
            writing = (isinstance(mode, str) and any(c in mode for c in "wax+")) or (isinstance(flags, int) and flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND))
            if writing:
                if isinstance(name, int):
                    require(stat.S_ISFIFO(os.fstat(name).st_mode), "only owned artifact pipes admitted by descriptor")
                else:
                    require(Path(name).resolve().is_relative_to(output), "inspection write escaped admitted output")

    sys.addaudithook(audit)
    (output / "STARTED.json").write_text(json.dumps({"started_unix": time.time()}) + "\n")
    sys.path.insert(0, str(root))
    from verification.bundle import strict_json

    def raw(name):
        require(name in scope["input_bindings"], "unbound inspection input")
        p = root / name
        require(p.is_file() and not p.is_symlink() and p.stat().st_size <= 16 * 1024**2, "nonregular or excessive inspection input")
        data = p.read_bytes()
        require(hashlib.sha256(data).hexdigest() == scope["input_bindings"][name], "inspection input differs: " + name)
        return data

    def doc(name):
        return strict_json(raw(name))

    require(str(Path(sys.executable).resolve()) == scope["interpreter"] and hashlib.sha256(Path(sys.executable).read_bytes()).hexdigest() == scope["interpreter_sha256"], "interpreter differs")
    raw(str(Path(__file__).resolve().relative_to(root)))
    boundary = doc("results/final-core-runtime-join-2026-10-28/BOUNDARY.json")
    metadata = doc(scope["artifact_metadata"])["artifacts"]
    jobs = doc(scope["job_metadata"])["jobs"]
    for selected in scope["artifacts"]:
        item = next(a for a in metadata if a["id"] == selected["id"])
        job = next(j for j in jobs if j["id"] == selected["job_id"])
        require(item["workflow_run"]["head_sha"] == boundary["compiled_source_commit"] and item["expired"] is False and item["digest"] == "sha256:" + selected["sha256"] and item["size_in_bytes"] <= selected["maximum_bytes"], "hosted artifact source, digest or bound differs")
        require(job["run_id"] == 40200780674 and job["conclusion"] == "success" and all(s["conclusion"] == "success" for s in job["steps"]), "hosted instrumentation steps incomplete")
    for name, sha in boundary["native_source_sha256"].items():
        require(hashlib.sha256(raw(name)).hexdigest() == sha, "final native source differs")
    records = []
    expected_cases = {"version", "core", "position", "rules", "evaluation", "table", "search", "notation", "uci", "position_line", "kernels", "dense_kernels", "neural_bounds", "evaluation_cache", "tactical_generation", "search_context", "lmr_window", "network_precision", "accumulator_stack", "state_probe", "search_claim", "search_probe"}
    for item, argv in zip(scope["artifacts"], admitted):
        path = output / (item["platform"] + "-tsan.zip")
        error_path = output / (item["platform"] + "-download.stderr")
        with path.open("xb") as target, error_path.open("xb") as error:
            os.chmod(path, 0o600)
            os.chmod(error_path, 0o600)
            env = dict(os.environ, GH_NO_UPDATE_NOTIFIER="1", GH_NO_EXTENSION_UPDATE_NOTIFIER="1", GH_PROMPT_DISABLED="1")
            process = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=error, env=env, start_new_session=True, preexec_fn=lambda: resource.setrlimit(resource.RLIMIT_FSIZE, (262144, 262144)))
            used = 0
            try:
                while chunk := process.stdout.read(65536):
                    used += len(chunk)
                    require(used <= item["maximum_bytes"], "artifact exceeds prepaid bound")
                    target.write(chunk)
                require(process.wait(timeout=10) == 0, "existing artifact download failed")
            finally:
                if process.poll() is None:
                    process.terminate()
                    try:
                        process.wait(timeout=2)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=2)
                process.stdout.close()
        with path.open("rb") as stream:
            observed_sha = hashlib.file_digest(stream, "sha256").hexdigest()
        require(observed_sha == item["sha256"] and error_path.stat().st_size == 0, "artifact digest or transport differs")
        with zipfile.ZipFile(path) as archive:
            entries = archive.infolist()
            names = [e.filename for e in entries]
            require(len(names) == len(set(names)) and sum(e.file_size for e in entries) <= 256 * 1024**2, "duplicate or excessive archive")
            require(all(not n.startswith("/") and ".." not in Path(n).parts for n in names), "unsafe archive member")

            def member(suffix, maximum=4 * 1024**2):
                found = [n for n in names if n.endswith(suffix)]
                require(len(found) == 1, "missing or aliased archive member: " + suffix)
                info = archive.getinfo(found[0])
                require(info.file_size <= maximum, "excessive metadata member")
                return archive.read(info)

            programs = strict_json(member("runs/native-state-programs.json"))
            cases = strict_json(member("runs/native-state-cases.json"))["tests"]
            commands = strict_json(member("build-state/compile_commands.json"))
            cache = member("build-state/CMakeCache.txt").decode()
            log = member("build-state/Testing/Temporary/LastTest.log").decode()
            require(programs["source_commit"] == boundary["compiled_source_commit"] and programs["instrumentation"] == "-fsanitize=thread", "archive is not exact-source TSan")
            require({c["name"] for c in cases} == expected_cases and len(cases) == 22, "native case inventory differs")
            require(commands and all("-fsanitize=thread" in c["command"] for c in commands) and "CAISSA_TSAN:BOOL=ON" in cache, "actual instrumentation flags absent")
            require(log.count("Test Passed.") == 22 and "Test Failed." not in log and "End testing:" in log and "WARNING: ThreadSanitizer" not in log, "native instrumentation did not complete cleanly")
            program_hashes = {}
            for original_name, expected in programs["programs"].items():
                base = Path(original_name).name
                found = [n for n in names if n.endswith("build-state/" + base)]
                require(len(found) == 1, "instrumented program missing or aliased")
                with archive.open(found[0]) as stream:
                    sha = hashlib.file_digest(stream, "sha256").hexdigest()
                require(sha == expected, "instrumented program bytes differ")
                program_hashes[base] = sha
            restoration = strict_json(member("runs/native-state-restoration/independent/RESTORATION.json"))
            draw = strict_json(member("runs/native-state-draw/independent/DRAW_HISTORY.json"))
            require(restoration["status"] == "passed" and restoration["pairs"] == 1280 and restoration["native_exit"] == 0 and draw["status"] == "passed" and draw["histories"] == 92 and draw["observations"] == 2195 and draw["native_exit"] == 0, "independent state/history archive results incomplete")
            require(restoration["engine_sha256"] == draw["engine_sha256"] == program_hashes["caissa"], "archive reader/program identities differ")
            records.append({"platform": item["platform"], "artifact_id": item["id"], "archive_sha256": observed_sha, "archive_bytes": used, "source_commit": programs["source_commit"], "instrumentation": programs["instrumentation"], "compiled_units": len(commands), "native_cases_passed": 22, "independent_restoration_pairs": 1280, "independent_draw_histories": 92, "program_sha256": program_hashes, "originals_executed_again": False})

    performance_root = "results/performance-v4-2026-10-26/"
    performance, reader = doc(performance_root + "PERFORMANCE.json"), doc(performance_root + "execution/independent.log")
    require(performance["scope_closed"] is True and reader["status"] == "passed" and performance["engine_sha256"] == reader["engine_sha256"] == boundary["engine_sha256"] and performance["network_sha256"] == reader["network_sha256"] == boundary["network_sha256"], "performance actor or completion differs")
    require(hashlib.sha256(raw(performance_root + "execution/independent.log")).hexdigest() == performance["independent_sha256"], "performance independent digest differs")
    for name in ["producer", "independent"]:
        stage = doc(performance_root + "execution/" + name + ".json")
        require(stage["exit"] == 0 and stage["reason"] == "completed" and stage["cleanup_warnings"] == [] and hashlib.sha256(raw(performance_root + "execution/" + name + ".log")).hexdigest() == stage["log_sha256"], "performance stage/log incomplete")
    require(reader["timed_searches"] == 640 and reader["rss_samples"] == 4581 and reader["latency_samples"] == 2000 and reader["independent_fixed_node_searches"] == 16, "performance full sample differs")
    tables = []
    for mode in ["classical", "neural-blend"]:
        rows = [p for p in reader["profiles"] if p["evaluation"] == mode]
        one = next(p for p in rows if p["threads"] == 1)
        require(sorted(p["threads"] for p in rows) == [1, 2, 4, 8], "missing thread mode")
        tables.extend({"evaluation": mode, "threads": p["threads"], "useful_nodes_per_second": p["useful_nodes_per_second"], "useful_work_ratio_to_one_thread": p["useful_nodes_per_second"] / one["useful_nodes_per_second"], "mean_depth": p["mean_depth"], "maximum_resident_bytes": p["maximum_resident_bytes"]} for p in rows)
    comparison_ids = ["threads-2-ms-100", "threads-2-ms-400", "threads-4-ms-100", "threads-4-ms-400", "threads-8-ms-100"]
    for name in comparison_ids:
        comparison = doc("runs/full-parallel-strength-v1/attempts/attempt-005/independent-" + name + ".log")
        require(comparison["status"] == "passed" and comparison["comparison"] == name and comparison["candidate_identity"]["executable"] == boundary["engine_sha256"] and comparison["candidate_identity"]["network_sha256"] == boundary["network_sha256"], "thread comparison identity differs")
    protocol = doc("results/final-saved-actor-protocol-2026-10-28/PROTOCOL_REPLAY.json")
    require(protocol["status"] == "passed" and protocol["engine_sha256"] == boundary["engine_sha256"] and protocol["stop_ms"]["p99"] < 50, "accepted G04 receipt differs")
    g04_scope = doc("work/final-protocol-runtime-1-2026-10-28/SCOPE.json")
    g04_source = raw("tools/protocol_campaign.py")
    require(hashlib.sha256(g04_source).hexdigest() == g04_scope["source_bindings"]["tools/protocol_campaign.py"] and b"setoption name Hash value 1" in g04_source and b"setoption name Hash value 2" in g04_source and b"EvalFile" not in g04_source and b"Use Neural" not in g04_source, "G04 option coverage cannot be derived from its pinned producer")
    result = {"status": "passed_partial_thread_evidence_join", "product_source_commit": scope["product_commit"], "saved_engine_sha256": boundary["engine_sha256"], "network_sha256": boundary["network_sha256"], "matched_native_files": len(boundary["native_source_sha256"]), "tsan_archives": records, "performance": {"timed_searches": 640, "rss_samples": 4581, "latency_samples": 2000, "source_binding_checked": True, "tables": tables}, "accepted_comparisons": comparison_ids, "G04_stop_ms": protocol["stop_ms"], "G04_configuration": {"hash_mib": [1, 2], "neural_model_loaded": False}, "remaining": ["Exact52d neural10/LazyNeural/cache/tactical/Hash16 configuration under race instrumentation across1/2/4/8threads", "Stop p99 under that same applied neural configuration with active-search witnesses", "Original sixth match comparison remains incomplete; no replacement time admitted"], "prior_incomplete_tactical_race_replay_preserved": True, "native_starts": 0, "games_started": 0, "closed_samples_reexecuted": 0, "full_R03_completed": False, "full_G10_certified": False, "original_compiler_runtime_closure_established": False, "full_acceptance": False, "elapsed_seconds": time.monotonic() - started}
    (output / "THREAD_EVIDENCE.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({"status": result["status"], "source_matched_TSan_archives": len(records), "native_cases_each": 22, "performance_thread_rows": len(tables), "native_starts": 0, "games_started": 0, "full_R03_completed": False, "elapsed_seconds": result["elapsed_seconds"]}))


if __name__ == "__main__":
    main(sys.argv[1])
