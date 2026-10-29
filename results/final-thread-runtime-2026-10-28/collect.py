"""Join the completed thread component to existing source and performance evidence."""

import copy
import fcntl
import hashlib
import json
import os
from pathlib import Path
import resource
import signal
import sys
import time


def require(value, reason):
    if not value:
        raise ValueError(reason)


def validate(report, boundary, profile):
    require(report["engine_sha256"] == boundary["engine_sha256"] and report["network_sha256"] == boundary["network_sha256"], "final actor/model differs")
    require(report["matched_native_files"] == 69 and report["compiled_source_commit"] == boundary["compiled_source_commit"], "native source relationship incomplete")
    require(report["options"] == profile["options"] and report["threads"] == [1, 2, 4, 8], "applied thread configuration differs")
    runtime = report["runtime"]
    require(runtime["stop_sequences"] == 4000 and runtime["instrumented_searches"] == 64 and runtime["native_sessions"] == 8 and runtime["all_native_exits_zero"] is True and runtime["forced_cleanup"] is False and runtime["critical_sanitizer_diagnostics"] == 0, "runtime endpoints or exits incomplete")
    require(runtime["stop_ms"]["count"] == 4000 and runtime["stop_ms"]["p99"] < 50 and set(runtime["stop_ms_per_thread"]) == {"1", "2", "4", "8"} and all(x["count"] == 1000 and x["p99"] < 50 for x in runtime["stop_ms_per_thread"].values()), "stop endpoint weakened or failed")
    require(report["accepted_comparisons"] == 5 and report["original_sixth_comparison"] == "closed incomplete", "incomplete match schedule reclassified")
    require(report["performance_diagnostic_difference"] == {"Search Stats": {"performance": True, "matches_and_stop_runtime": False}}, "performance diagnostic configuration hidden")
    require(report["strength_gain_inferred"] is False and report["full_G10_certified"] is False and report["full_acceptance"] is False and report["original_compiler_runtime_closure_established"] is False, "unsupported strength, compiler or release claim")


def main(path):
    os.umask(0o077)
    start = time.monotonic()
    path = Path(path).resolve()
    scope = json.loads(path.read_text())
    root, output = Path(scope["root"]), path.parent
    require(scope["status"] == "admitted" and time.time() < scope["deadline_unix"] and not (output / "STARTED.json").exists(), "one fresh finite metadata invocation required")
    lease = (root / "runs/TIMED_STRENGTH.lock").open("r+")
    fcntl.flock(lease.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    resource.setrlimit(resource.RLIMIT_CPU, (20, 20))
    resource.setrlimit(resource.RLIMIT_FSIZE, (262144, 262144))

    def stop(*_):
        raise TimeoutError("thread join deadline exhausted")

    signal.signal(signal.SIGALRM, stop)
    signal.setitimer(signal.ITIMER_REAL, min(20, scope["deadline_unix"] - time.time()))

    def audit(event, args):
        if event.startswith("socket.") or event in {"subprocess.Popen", "os.system", "os.posix_spawn", "os.exec"}:
            raise RuntimeError("thread join prohibits processes and network")
        if event == "open":
            name, mode, flags = args
            writing = (isinstance(mode, str) and any(c in mode for c in "wax+")) or (isinstance(flags, int) and flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND))
            if writing:
                require(not isinstance(name, int) and Path(name).resolve().parent == output and Path(name).name in {"STARTED.json", "THREAD_PERFORMANCE_JOIN.json"}, "thread join write escaped finite namespace")

    sys.addaudithook(audit)
    (output / "STARTED.json").write_text(json.dumps({"unix": time.time()}) + "\n")
    require(str(Path(sys.executable).resolve()) == scope["interpreter"] and hashlib.sha256(Path(sys.executable).read_bytes()).hexdigest() == scope["interpreter_sha256"], "join interpreter differs")
    for name, sha in scope["input_bindings"].items():
        require(not (root / name).is_symlink() and hashlib.sha256((root / name).read_bytes()).hexdigest() == sha, "bound join input differs: " + name)

    def doc(name):
        require(name in scope["input_bindings"], "unbound join document")
        return json.loads((root / name).read_text())

    boundary = doc("results/final-core-runtime-join-2026-10-28/BOUNDARY.json")
    for name, sha in boundary["native_source_sha256"].items():
        require(scope["input_bindings"][name] == sha and bool((root / name).stat().st_mode & 0o111) == (boundary["native_source_modes"][name] == "100755"), "current native source/mode differs")
    profile = doc("config/thread-runtime-v1.json")
    partial = doc("results/final-thread-evidence-2026-10-28/THREAD_EVIDENCE.json")
    reader = scope["reader_directory"]
    runtime, join, closed = [doc(reader + "/" + n) for n in ["THREAD_RUNTIME.json", "READER_JOIN.json", "CLOSED.json"]]
    require(closed["closed"] and closed["owner_exit"] == 0 and closed["stderr_bytes"] == 0 and join["status"] == "passed_reader_only_correction" and join["new_native_starts"] == 0 and join["reader_result_sha256"] == scope["input_bindings"][reader + "/THREAD_RUNTIME.json"], "actual independent reader/exit binding incomplete")
    require(runtime["profile_sha256"] == scope["input_bindings"]["config/thread-runtime-v1.json"] and runtime["engine_sha256"] == partial["saved_engine_sha256"] == boundary["engine_sha256"] and runtime["network_sha256"] == partial["network_sha256"] == boundary["network_sha256"], "runtime/partial/core actor differs")
    require(all(a["source_commit"] == boundary["compiled_source_commit"] and a["native_cases_passed"] == 22 for a in partial["tsan_archives"]) and partial["tsan_archives"][1]["program_sha256"]["caissa"] == runtime["instrumented_engine_sha256"], "instrumented source/archive actor differs")
    perfdir = "results/performance-v4-2026-10-26"
    perf, lineage, independent = [doc(perfdir + "/" + n) for n in ["PERFORMANCE.json", "DEPLOYMENT_LINEAGE.json", "execution/independent.log"]]
    require(perf["scope_closed"] and independent["status"] == "passed" and independent["timed_searches"] == 640 and independent["rss_samples"] == 4581 and independent["independent_fixed_node_searches"] == 16, "original performance endpoint incomplete")
    require(perf["engine_sha256"] == lineage["engine_sha256"] == boundary["engine_sha256"] and perf["network_sha256"] == lineage["network_sha256"] == boundary["network_sha256"] and lineage["checkpoint_sha256"] == boundary["checkpoint_sha256"], "performance final deployment actor/model/checkpoint differs")
    for stage in ["producer", "independent"]:
        record = doc(perfdir + "/execution/" + stage + ".json")
        require(record["exit"] == 0 and record["reason"] == "completed" and record["cleanup_warnings"] == [] and record["log_sha256"] == scope["input_bindings"][perfdir + "/execution/" + record["log"]], "performance stage/log/cleanup differs")
    require(perf["independent_sha256"] == scope["input_bindings"][perfdir + "/execution/independent.log"], "performance independent receipt differs")
    comparisons = []
    for name in partial["accepted_comparisons"]:
        comparison = doc("runs/full-parallel-strength-v1/attempts/attempt-005/independent-" + name + ".log")
        require(comparison["status"] == "passed" and comparison["statistics"]["games"] == 200 and comparison["full_G10_certified"] is False, "original comparison result differs")
        for actor in [comparison["candidate_identity"], comparison["opponent_identity"]]:
            require(actor["executable"] == boundary["engine_sha256"] and actor["network_sha256"] == boundary["network_sha256"], "thread comparison actor/model differs")
            require(all(actor["options"].get(k, False if k == "Search Stats" else None) == v for k, v in profile["options"].items()), "thread comparison options differ")
        comparisons.append({"comparison": name, "games": 200, "relative_elo": comparison["statistics"]["elo_difference"], "relative_elo_95": comparison["statistics"]["elo_95"]})
    report = {"status": "passed_final_thread_performance_relationships", "engine_sha256": boundary["engine_sha256"], "network_sha256": boundary["network_sha256"], "compiled_source_commit": boundary["compiled_source_commit"], "matched_native_files": 69, "options": profile["options"], "threads": [1, 2, 4, 8], "runtime": runtime, "accepted_comparisons": len(comparisons), "comparisons": comparisons, "original_sixth_comparison": "closed incomplete", "performance": partial["performance"], "performance_diagnostic_difference": {"Search Stats": {"performance": True, "matches_and_stop_runtime": False}}, "first_and_second_failed_owner_receipts_preserved": True, "strength_gain_inferred": False, "full_G10_certified": False, "original_compiler_runtime_closure_established": False, "full_acceptance": False}
    validate(report, boundary, profile)
    cases = [
        ("wrong-final-actor", lambda r: r.update(engine_sha256="0"*64)),
        ("changed-hash", lambda r: r["options"].update(Hash=32)),
        ("missing-stop", lambda r: r["runtime"].update(stop_sequences=3999)),
        ("failed-eight-thread-p99", lambda r: r["runtime"]["stop_ms_per_thread"]["8"].update(p99=50)),
        ("missing-instrumented-search", lambda r: r["runtime"].update(instrumented_searches=63)),
        ("forced-cleanup", lambda r: r["runtime"].update(forced_cleanup=True)),
        ("sixth-match-reclassified", lambda r: r.update(original_sixth_comparison="passed")),
        ("performance-diagnostic-hidden", lambda r: r.update(performance_diagnostic_difference={})),
        ("strength-inferred-from-performance", lambda r: r.update(strength_gain_inferred=True)),
        ("full-G10-from-components", lambda r: r.update(full_G10_certified=True)),
        ("original-runtime-claim", lambda r: r.update(original_compiler_runtime_closure_established=True)),
        ("release-claim", lambda r: r.update(full_acceptance=True)),
    ]
    controls = []
    for name, mutate in cases:
        forged = copy.deepcopy(report)
        mutate(forged)
        try:
            validate(forged, boundary, profile)
        except ValueError as error:
            controls.append({"case": name, "status": "rejected", "reason": str(error)})
        else:
            raise ValueError("forged final relationship accepted: " + name)
    report.update(negative_controls=controls, elapsed_seconds=time.monotonic()-start, new_native_starts=0, games_started=0, semantic_sample_reruns=0, product_source_commit=scope["product_commit"])
    (output / "THREAD_PERFORMANCE_JOIN.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"status": report["status"], "negative_controls": len(controls), "matched_native_files": 69, "new_native_starts": 0, "elapsed_seconds": report["elapsed_seconds"]}))


if __name__ == "__main__":
    main(sys.argv[1])
