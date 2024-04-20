"""Bind a report to the closed external sample, without replaying moves or actors."""

import copy
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import re
import resource
import signal
import stat
import sys
import time


def require(value, reason):
    if not value:
        raise ValueError(reason)


def validate(report, actor, profile):
    require(report["absolute_elo"] is None and report["default_classical_rating"] is None and report["full_acceptance"] is False, "unsupported absolute/default/release claim")
    require(report["actor"]["engine_sha256"] == actor["engine_sha256"] and report["actor"]["network_sha256"] == actor["network_sha256"], "wrong saved actor or network")
    require(report["actor"]["options"] == {"Threads": 1, "Hash": 16, "Ordering Hints": False, "Neural Bounds": False, "Evaluation Cache": True, "Tactical Generation": True, "Use Neural": True, "Neural Weight": 10, "Lazy Neural": True}, "measured neural configuration changed")
    require(report["conditions"] == {k: profile["matches"][k] for k in ["milliseconds", "threads", "hash_mib", "warmup_nodes", "transport_allowance_ms", "maximum_plies", "workers", "bootstrap_resamples", "bootstrap_seed", "confidence"]}, "time/resource/uncertainty conditions changed")
    require([s["games"] for s in report["settings"]] == [668, 666, 666], "fixed external schedule differs")
    for row, expected_name in zip(report["settings"], profile["matches"]["external_settings"]):
        require(row["name"] == expected_name and row["opponent_sha256"] == profile["matches"]["stockfish_sha256"], "opponent version or setting differs")
        require(row["wins"] + row["draws"] + row["losses"] == row["games"] and row["unfinished"] == 0, "missing or unfinished original outcomes")
        require(row["relative_elo_95"][0] <= row["relative_elo"] <= row["relative_elo_95"][1], "uncertainty interval differs")
        score = (row["wins"] + row["draws"] / 2) / row["games"]
        require(abs(400 * math.log10(score / (1 - score)) - row["relative_elo"]) < 1e-9, "relative point estimate differs from outcomes")


def main(scope_path):
    started = time.monotonic()
    scope_path = Path(scope_path).resolve()
    scope = json.loads(scope_path.read_text())
    root, output = Path(scope["root"]), scope_path.parent
    require(scope["status"] == "admitted" and time.time() < scope["deadline_unix"] and not (output / "STARTED.json").exists(), "one fresh finite invocation required")
    lease = (root / "runs/TIMED_STRENGTH.lock").open("r+")
    fcntl.flock(lease.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    resource.setrlimit(resource.RLIMIT_CPU, (20, 20))
    resource.setrlimit(resource.RLIMIT_FSIZE, (512000, 512000))

    def stop(*_):
        raise TimeoutError("external report join deadline exhausted")

    signal.signal(signal.SIGALRM, stop)
    signal.setitimer(signal.ITIMER_REAL, min(20, scope["deadline_unix"] - time.time()))

    def audit(event, args):
        if event.startswith("socket.") or event in {"subprocess.Popen", "os.system", "os.posix_spawn", "os.exec"}:
            raise RuntimeError("external report join prohibits processes and network")
        if event == "open":
            name, mode, flags = args
            writing = (isinstance(mode, str) and any(c in mode for c in "wax+")) or (isinstance(flags, int) and flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND))
            if writing:
                require(not isinstance(name, int) and Path(name).resolve().is_relative_to(output), "report write escaped output")

    sys.addaudithook(audit)
    (output / "STARTED.json").write_text(json.dumps({"started_unix": time.time()}) + "\n")
    sys.path.insert(0, str(root))
    from verification.bundle import strict_json

    def raw(name):
        require(name in scope["input_bindings"], "unbound report input")
        p = root / name
        require(not p.is_symlink() and stat.S_ISREG(p.stat().st_mode) and p.stat().st_size <= 16 * 1024**2, "linked/nonregular/excessive report input")
        data = p.read_bytes()
        require(hashlib.sha256(data).hexdigest() == scope["input_bindings"][name], "report input hash differs: " + name)
        return data

    def doc(name):
        return strict_json(raw(name))

    require(str(Path(sys.executable).resolve()) == scope["interpreter"], "interpreter differs")
    require(hashlib.sha256(Path(sys.executable).read_bytes()).hexdigest() == scope["interpreter_sha256"], "interpreter bytes differ")
    raw(str(Path(__file__).resolve().relative_to(root)))
    for name in ["verification/bundle.py", "verification/source.py"]:
        raw(name)
    public, run = "results/external-v4-2026-10-26", "runs/full-external-strength-v4"
    evidence = doc(public + "/EVIDENCE.json")
    for name, sha in evidence["files"].items():
        require(hashlib.sha256(raw(public + "/" + name)).hexdigest() == sha, "original external publication differs")
    proof, profile = doc(public + "/independent-external.json"), doc(public + "/PROTOCOL.json")
    campaign, active = doc(run + "/STRENGTH_CAMPAIGN.json"), doc(run + "/ACTIVE_USAGE.json")
    require(campaign["scope_closed"] is True and active["closed"] is True and campaign["failed_domains"] == [], "external sample not closed successfully")
    require(campaign == doc(public + "/STRENGTH_CAMPAIGN.json") and proof["status"] == "passed" and proof["games"] == 2000, "original campaign or independent receipt differs")
    boundary = doc("results/final-core-runtime-join-2026-10-28/BOUNDARY.json")
    core = doc("results/final-core-runtime-join-2026-10-28/CORE_RUNTIME_JOIN.json")
    actor = profile["strength_actor"]
    require(boundary["engine_sha256"] == core["engine_sha256"] == actor["engine_sha256"] and boundary["network_sha256"] == core["network_sha256"] == actor["network_sha256"] and boundary["compiled_source_commit"] == actor["compiled_source_commit"], "final core/source/strength actor differs")
    require(hashlib.sha256(raw("runs/full-parallel-strength-v1/bin/caissa")).hexdigest() == actor["engine_sha256"] and hashlib.sha256(raw("runs/full-parallel-strength-v1/inputs/selected.cai")).hexdigest() == actor["network_sha256"], "retained final actor bytes differ")
    for name, expected in boundary["native_source_sha256"].items():
        require(hashlib.sha256(raw(name)).hexdigest() == expected, "current native input differs from accepted core boundary")
        require(bool((root / name).stat().st_mode & 0o111) == (boundary["native_source_modes"][name] == "100755"), "current native mode differs")
    attempt = run + "/attempts/attempt-001/"
    stages = [doc(attempt + name + ".json") for name in ["play-external-0", "statistics-external-0", "play-external-1", "statistics-external-1", "play-external-2", "statistics-external-2", "independent-external"]]
    require(all(type(s["exit"]) is int and s["exit"] == 0 and s["reason"] == "completed" and s["cleanup_warnings"] == [] for s in stages), "original stage failed or cleanup incomplete")
    require(stages[-1]["log_sha256"] == hashlib.sha256(raw(public + "/independent-external.json")).hexdigest() == campaign["independent_artifact"]["sha256"], "independent stage/result binding differs")
    host = doc(run + "/HOST_START_1.json")
    report = {"status": "passed_final_external_report_join", "actor": {"engine_sha256": actor["engine_sha256"], "network_sha256": actor["network_sha256"], "compiled_source_commit": actor["compiled_source_commit"], "historical_campaign_source_commit": campaign["source_commit"], "options": {}}, "conditions": {k: profile["matches"][k] for k in ["milliseconds", "threads", "hash_mib", "warmup_nodes", "transport_allowance_ms", "maximum_plies", "workers", "bootstrap_resamples", "bootstrap_seed", "confidence"]}, "hardware": {"recorded_platform": host["platform"], "recorded_logical_cpus": host["cpu_count"], "cpu_brand_and_ram": "not captured by the original campaign host receipt"}, "settings": [], "absolute_elo": None, "default_classical_rating": None, "full_acceptance": False}
    pgn_counts = []
    for i, setting in enumerate(proof["settings"]):
        candidate, opponent = setting["candidate_identity"], setting["opponent_identity"]
        require(candidate["executable"] == actor["engine_sha256"] and candidate["network_sha256"] == actor["network_sha256"], "candidate differs across settings")
        options = {k: v for k, v in candidate["options"].items() if k != "EvalFile"}
        require(not report["actor"]["options"] or report["actor"]["options"] == options, "settings use different candidate options")
        report["actor"]["options"] = options
        stats = setting["statistics"]
        summary = doc(public + f"/external-{i}-SUMMARY.json")
        require(all(summary[k] == v for k, v in stats.items()) and summary["bootstrap"] == {"unit": "opening family containing color-reversed pairs", "resamples": 20000, "seed": 104729}, "accepted statistics or bootstrap differs")
        require(stages[2*i+1]["log_sha256"] == hashlib.sha256(raw(public + f"/external-{i}-SUMMARY.json")).hexdigest(), "statistics stage/summary binding differs")
        counts, pairs = {"wins": 0, "draws": 0, "losses": 0}, {}
        names = sorted(scope["pgn_inputs"][str(i)])
        actual_names = sorted(str(p.relative_to(root)) for p in (root / run / f"external-{i}/games").iterdir())
        require(names == actual_names, "retained PGN inventory differs")
        for name in names:
            header = raw(name).split(b"\n\n", 1)[0].decode("utf8")
            tags = dict(re.findall(r'^\[([^ ]+) "([^"]*)"\]$', header, re.MULTILINE))
            require(tags["Result"] in {"1-0", "0-1", "1/2-1/2"}, "unfinished original PGN")
            white = tags["White"] == "Caissa validation-selected original model"
            require(tags["Black" if white else "White"] == setting["setting"], "PGN actor label differs")
            key = "draws" if tags["Result"] == "1/2-1/2" else "wins" if (tags["Result"] == "1-0") == white else "losses"
            counts[key] += 1
            pairs.setdefault(tags["OpeningId"], []).append(white)
        require(all(stats[k] == v for k, v in counts.items()) and len(pairs) == stats["complete_pairs"] and all(sorted(v) == [False, True] for v in pairs.values()), "retained PGN outcomes or color pairs differ")
        pgn_counts.append({"setting": i, **counts, "paired_openings": len(pairs), "pgn_files": len(names)})
        report["settings"].append({"name": setting["setting"], "opponent_sha256": opponent["executable"], "opponent_options": opponent["options"], "games": stats["games"], "wins": stats["wins"], "draws": stats["draws"], "losses": stats["losses"], "unfinished": stats["unfinished_games"], "pairs": stats["complete_pairs"], "relative_elo": stats["elo_difference"], "relative_elo_95": stats["elo_95"]})
    validate(report, actor, profile)
    controls = []
    for name, mutate in [
        ("absolute-rating", lambda r: r.update(absolute_elo=2000)),
        ("default-classical-rating", lambda r: r.update(default_classical_rating=2000)),
        ("release-flag", lambda r: r.update(full_acceptance=True)),
        ("wrong-engine", lambda r: r["actor"].update(engine_sha256="0"*64)),
        ("public-defaults-substituted", lambda r: r["actor"]["options"].update(Hash=32, **{"Use Neural": False})),
        ("wrong-time-control", lambda r: r["conditions"].update(milliseconds=1000)),
        ("unfinished-original-game", lambda r: r["settings"][2].update(unfinished=1)),
        ("changed-opponent", lambda r: r["settings"][2].update(opponent_sha256="0"*64)),
    ]:
        forged = copy.deepcopy(report)
        mutate(forged)
        try:
            validate(forged, actor, profile)
        except ValueError as error:
            controls.append({"case": name, "status": "rejected", "reason": str(error)})
        else:
            raise ValueError("incorrect report accepted: " + name)
    report.update({"product_source_commit": scope["product_commit"], "core_source_join_sha256": scope["input_bindings"]["results/final-core-runtime-join-2026-10-28/CORE_RUNTIME_JOIN.json"], "matched_native_files": len(boundary["native_source_sha256"]), "retained_pgn_header_counts": pgn_counts, "negative_controls": controls, "elapsed_seconds": time.monotonic() - started, "native_starts": 0, "games_started": 0, "move_replays": 0, "bootstrap_reruns": 0, "original_compiler_runtime_closure_established": False, "full_bundle_coordinator_executed": False})
    (output / "EXTERNAL_REPORT.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"status": report["status"], "retained_pgn_headers": sum(x["pgn_files"] for x in pgn_counts), "settings": len(report["settings"]), "controls": len(controls), "elapsed_seconds": report["elapsed_seconds"], "full_acceptance": False}))


if __name__ == "__main__":
    main(sys.argv[1])
