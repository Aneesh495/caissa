"""Final core, external-report and performance evidence adapters.

Accepted independent joins are reused through their fixed inputs, actual exits
and current source relationships. No native sample or historical control runs.
"""

import hashlib
import json

from verification.final_evidence_bundle import (
    ANCHORS, ENGINE, NETWORK, Records, boundary, owner, source_bytes, stage,
)
from verification.source import require


CORE = "work/final-core-runtime-join-1-2026-10-28/"
EXTERNAL = "work/final-external-report-1-2026-10-28/"
PERFORMANCE = "work/final-thread-performance-join-1-2026-10-28/"
BOUNDARY = "results/final-core-runtime-join-2026-10-28/BOUNDARY.json"
FAMILIES = {
    "core": (CORE, "CORE_RUNTIME_JOIN.json", "results/final-core-runtime-join-2026-10-28/CORE_RUNTIME_JOIN.json", "33d97f060b0395576d333ebde6a3246b7143bf96ea2faaa0e3f0c0c7687d0c7f", "752873744fe92e31ef8d6f3e2d4869bbc2518c5bc21a67ee3c2f557eb303f124"),
    "external": (EXTERNAL, "EXTERNAL_REPORT.json", "results/final-external-report-2026-10-28/EXTERNAL_REPORT.json", "1427d4ae1c12710592284e854aab92102020653854670f555ecd386e369aa788", "6ec5296ef552f05942fc7e612dc93212e80a17a53c7fc4ae9d57cebc5d94abdf"),
    "performance": (PERFORMANCE, "THREAD_PERFORMANCE_JOIN.json", "results/final-thread-runtime-2026-10-28/THREAD_PERFORMANCE_JOIN.json", "58ccc182d0bc9167b05a97ef319863dfcecac9261dd11fae6e5ec9e2179c9572", "0cbf83c6223673782b56bc2a66637771f13e13c6f2ea85be895a803a0c818893"),
}
CORE_GATES = {f"G{i:02d}" for i in range(1, 7)}
DRIVERS = {**{g: "final-core-runtime-evidence-v1" for g in CORE_GATES}, "G09": "final-external-report-evidence-v1", "G13": "final-performance-evidence-v1"}
DOMAINS = {
    "G01": ("rules", "RULES.json", "independent/", "verification/rules.py"),
    "G02": ("restoration", "RESTORATION.json", "independent/", "verification/restoration.py"),
    "G03": ("draw", "DRAW_HISTORY.json", "independent/", "verification/draw_history.py"),
    "G04": ("protocol", "PROTOCOL_REPLAY.json", "", "verification/protocol.py"),
    "G06": ("numerical", "NUMERICAL_REPLAY.json", "", "verification/numerical.py"),
}
for _gate in DRIVERS:
    _family = "core" if _gate in CORE_GATES else "external" if _gate == "G09" else "performance"
    _work, _result, _public, _scope_sha, _result_sha = FAMILIES[_family]
    ANCHORS[_gate] = {_work + "SCOPE.json": _scope_sha, _work + _result: _result_sha, BOUNDARY: "c7f46036d528f057c797e87994cfc2e03467f24b16c05d329655e48187199e25"}


def metadata_inputs(scope):
    """Retained metadata, not retired corpora, checkpoints or per-move games."""
    return {name for name in scope["input_bindings"] if name.startswith(("work/", "runs/", "results/")) and not name.endswith((".pgn", ".zip", ".pt", ".cai")) and not name.endswith("/bin/caissa")}


def same(a, b):
    return json.dumps(a, sort_keys=True, separators=(",", ":")) == json.dumps(b, sort_keys=True, separators=(",", ":"))


def sources(checkout, bindings, names):
    for name in names:
        require(name in bindings and hashlib.sha256(source_bytes(checkout, name)).hexdigest() == bindings[name], "executed final reader/producer source differs: " + name)


def family(records, checkout, kind):
    work, name, public, _, _ = FAMILIES[kind]
    scope, result = records.doc(work + "SCOPE.json"), records.doc(work + name)
    owner(records, work, records.sha(work + "SCOPE.json"))
    require(same(result, records.doc(public)) and result["full_acceptance"] is False, "published final join differs from actual independent output")
    expected = metadata_inputs(scope)
    require(expected <= set(records.records), "accepted join metadata inventory incomplete")
    for path in expected:
        require(records.sha(path) == scope["input_bindings"][path], "accepted join input bytes changed: " + path)
    summary = records.doc(work + "owner.stdout")
    require(summary["status"] == result["status"], "actual final join stdout differs")
    b = records.doc(BOUNDARY)
    boundary(checkout, b)
    sources(checkout, scope["input_bindings"], ["results/" + {"core": "final-core-runtime-join-2026-10-28", "external": "final-external-report-2026-10-28", "performance": "final-thread-runtime-2026-10-28"}[kind] + "/collect.py"])
    return scope, result, b


def core(records, checkout, gate):
    joined_scope, joined, b = family(records, checkout, "core")
    require(joined["status"] == "passed_core_runtime_evidence_join" and set(joined["domains"]) == CORE_GATES and joined["matched_native_files"] == 69, "final core join incomplete")
    require(joined["engine_sha256"] == ENGINE and joined["network_sha256"] == NETWORK and joined["semantic_sample_reruns"] == 0, "final core join actor or scope differs")
    if gate == "G05":
        # The accepted core join verified the archive and both real exits. Its
        # exact scope, source, result and actual successful owner are bound above.
        # Only the retained independent result is read here; no archive is replayed.
        report = records.doc("results/search-semantics-2026-10-25/SEARCH_SEMANTICS.json")
        require(report["source_commit"] == b["compiled_source_commit"] and report["observations"] == 3080 and report["native_exit"] == 0, "accepted search runtime/source differs")
        index = records.doc("results/search-semantics-2026-10-25/RAW_INDEX.json")
        source_manifest = records.doc("derived/G05_SOURCE_INPUTS.json")
        require(records.sha("derived/G05_SOURCE_INPUTS.json") == index["semantic-attempt-001/full-bundle/SOURCE_INPUTS.json"] and source_manifest["commit"] == b["compiled_source_commit"], "archived G05 reader source metadata differs")
        sources(checkout, source_manifest["files"], ["verification/search_semantics.py"])
    else:
        kind, name, prefix, reader = DOMAINS[gate]
        run = "runs/final-saved-actor-" + kind + "-2026-10-28/"
        work = "work/final-" + kind + "-runtime-1-2026-10-28/"
        public = "results/final-saved-actor-" + kind + "-2026-10-28/"
        scope, closed = records.doc(work + "SCOPE.json"), records.doc(work + "CLOSED.json")
        require(closed["closed"] is True and type(closed["owner_exit"]) is int and closed["owner_exit"] == 0 and closed["independent_closure_error"] is None and closed["scope_sha256"] == records.sha(work + "SCOPE.json"), "actual core owner failed or differs")
        active, writes = records.doc(run + "ACTIVE_USAGE.json"), records.doc(work + "WRITE_USAGE.json")
        require(active["closed"] is True and writes["closed"] is True and writes.get("failure") is None and writes["native_starts"] == scope["maximum_native_actor_starts"], "core active/write/native ledger incomplete")
        report = records.doc(run + prefix + name)
        require(same(report, records.doc(public + name)), "published core reader differs from actual artifact")
        for label in ["produce", "independent"]:
            stage(records, run, label)
        sources(checkout, scope["source_bindings"], [reader])
        require(scope["product_commit"] == joined["domains"][gate]["source_commit"] and report.get("profile_sha256", scope.get("profile_sha256")) == joined["domains"][gate]["profile_sha256"], "core executed profile/source differs")
    require(report["status"] == "passed" and report["full_acceptance"] is False and report["engine_sha256"] == ENGINE, "core actual independent reader did not pass")
    require(hashlib.sha256(json.dumps(report, sort_keys=True).encode()).hexdigest() == joined["domains"][gate]["reader_sha256"], "core reader differs from accepted final relationship join")
    if "network_sha256" in report:
        require(report["network_sha256"] == NETWORK, "core evaluator differs")
    if gate == "G06":
        require(report["checkpoint_sha256"] == b["checkpoint_sha256"] and report["probes"] == 100000 and report["float64_quantized_cp"]["max"] < 32 and report["test_arrays_opened"] is False, "selected numerical endpoint differs")
    return {"accepted_final_join_sha256": records.sha(CORE + "CORE_RUNTIME_JOIN.json"), "actual_independent_result_sha256": hashlib.sha256(json.dumps(report, sort_keys=True).encode()).hexdigest(), "current_native_files_and_modes": 69, "semantic_sample_replays": 0, "fresh_archive_replay": False}


def external(records, checkout):
    _, report, b = family(records, checkout, "external")
    require(report["status"] == "passed_final_external_report_join" and report["absolute_elo"] is None and report["default_classical_rating"] is None and report["move_replays"] == report["bootstrap_reruns"] == 0, "external final report or rating scope differs")
    require(report["actor"]["engine_sha256"] == ENGINE and report["actor"]["network_sha256"] == NETWORK and report["actor"]["compiled_source_commit"] == b["compiled_source_commit"], "external actor/source relationship differs")
    public, run = "results/external-v4-2026-10-26/", "runs/full-external-strength-v4/"
    profile, independent = records.doc(public + "PROTOCOL.json"), records.doc(public + "independent-external.json")
    campaign, active = records.doc(run + "STRENGTH_CAMPAIGN.json"), records.doc(run + "ACTIVE_USAGE.json")
    require(campaign["scope_closed"] is True and campaign["failed_domains"] == [] and active["closed"] is True and independent["status"] == "passed" and independent["games"] == 2000, "original external campaign or result incomplete")
    expected_options = {"Threads": 1, "Hash": 16, "Ordering Hints": False, "Neural Bounds": False, "Evaluation Cache": True, "Tactical Generation": True, "Use Neural": True, "Neural Weight": 10, "Lazy Neural": True}
    require(report["actor"]["options"] == expected_options and report["conditions"] == {k: profile["matches"][k] for k in report["conditions"]}, "external applied options or timing changed")
    require([r["games"] for r in report["settings"]] == [668, 666, 666] and report["retained_pgn_header_counts"] and len(report["retained_pgn_header_counts"]) == 3, "accepted original external schedule differs")
    attempt = run + "attempts/attempt-001/"
    for i, row in enumerate(report["settings"]):
        require(row["unfinished"] == 0 and row["wins"] + row["draws"] + row["losses"] == row["games"] and row["opponent_sha256"] == profile["matches"]["stockfish_sha256"], "external outcomes/comparator differ")
        for label in ["play-external-" + str(i), "statistics-external-" + str(i)]:
            receipt = records.doc(attempt + label + ".json")
            require(type(receipt["exit"]) is int and receipt["exit"] == 0 and receipt["reason"] == "completed" and receipt["cleanup_warnings"] == [], "actual original external stage failed")
        require(records.doc(attempt + "statistics-external-" + str(i) + ".json")["log_sha256"] == records.sha(public + "external-" + str(i) + "-SUMMARY.json"), "external statistics stage/result differ")
    receipt = records.doc(attempt + "independent-external.json")
    require(receipt["exit"] == 0 and receipt["cleanup_warnings"] == [] and receipt["log_sha256"] == records.sha(public + "independent-external.json") == campaign["independent_artifact"]["sha256"], "actual external independent stage/result differ")
    return {"accepted_final_join_sha256": records.sha(EXTERNAL + "EXTERNAL_REPORT.json"), "original_independently_checked_games": 2000, "PGN_header_and_move_replays": 0, "bootstrap_reruns": 0, "absolute_elo": None, "default_classical_rating": None, "full_historical_raw_reproduction": False}


def performance(records, checkout):
    scope, joined, b = family(records, checkout, "performance")
    sources(checkout, scope["input_bindings"], ["config/thread-runtime-v1.json"])
    require(joined["options"] == json.loads(source_bytes(checkout, "config/thread-runtime-v1.json"))["options"], "current frozen thread options differ")
    require(joined["status"] == "passed_final_thread_performance_relationships" and joined["engine_sha256"] == ENGINE and joined["network_sha256"] == NETWORK and joined["matched_native_files"] == 69, "final performance/source relationship differs")
    require(joined["original_sixth_comparison"] == "closed incomplete" and joined["accepted_comparisons"] == 5 and joined["full_G10_certified"] is False and joined["strength_gain_inferred"] is False and joined["original_compiler_runtime_closure_established"] is False, "performance result reclassified a failed/incomplete gate")
    prefix = "results/performance-v4-2026-10-26/"
    original, lineage, reader = records.doc(prefix + "PERFORMANCE.json"), records.doc(prefix + "DEPLOYMENT_LINEAGE.json"), records.doc(prefix + "execution/independent.log")
    require(original["scope_closed"] is True and reader["status"] == "passed" and reader["timed_searches"] == 640 and reader["rss_samples"] == 4581 and reader["independent_fixed_node_searches"] == 16, "original independent performance endpoint incomplete")
    require(original["engine_sha256"] == lineage["engine_sha256"] == ENGINE and original["network_sha256"] == lineage["network_sha256"] == NETWORK and lineage["checkpoint_sha256"] == b["checkpoint_sha256"], "performance deployment identity differs")
    for label in ["producer", "independent"]:
        stage(records, prefix + "execution/", label)
    require(original["independent_sha256"] == records.sha(prefix + "execution/independent.log"), "performance independent result differs")
    repair = scope["reader_directory"] + "/"
    require(records.doc(repair + "CLOSED.json")["owner_exit"] == 0 and records.doc(repair + "READER_JOIN.json")["reader_result_sha256"] == records.sha(repair + "THREAD_RUNTIME.json"), "accepted thread reader correction differs")
    require(joined["performance_diagnostic_difference"] == {"Search Stats": {"performance": True, "matches_and_stop_runtime": False}}, "performance diagnostic settings hidden")
    return {"accepted_final_join_sha256": records.sha(PERFORMANCE + "THREAD_PERFORMANCE_JOIN.json"), "original_timed_searches": 640, "original_rss_samples": 4581, "original_independent_fixed_node_searches": 16, "performance_is_descriptive": True, "new_stop_or_race_measurements": 0, "strength_inferred": False, "full_G10_certified": False}


def verify(bundle, inputs, checkout, expected_commit, gate):
    domain = inputs["domains"][gate]
    require(gate in DRIVERS and domain["driver"] == DRIVERS[gate] and domain["source_commit"] == expected_commit, "unsupported or stale final core/report/performance dispatch")
    require(domain["engine_sha256"] == inputs["engine"]["sha256"] == ENGINE and domain["network_sha256"] == inputs["network"]["artifact"]["sha256"] == NETWORK, "final adapter changed saved deployment")
    records = Records(bundle, domain, gate)
    details = core(records, checkout, gate) if gate in CORE_GATES else external(records, checkout) if gate == "G09" else performance(records, checkout)
    return {"status": "passed_final_closed_evidence_adapter", "gate": gate, "full_gate": True, "full_acceptance": False, "coordinator_source_commit": expected_commit, "engine_sha256": ENGINE, "network_sha256": NETWORK, "native_starts_in_this_adapter": 0, "semantic_sample_replays": 0, "original_compiler_runtime_closure": False, **details}


def integrate(bundle, inputs, checkout, expected_commit, review):
    accepted = []
    for gate, driver in sorted(DRIVERS.items()):
        if inputs["domains"][gate].get("driver") != driver:
            continue
        review.setdefault("verified_semantic_gates", {})[gate] = verify(bundle, inputs, checkout, expected_commit, gate)
        review["pending_semantic_gates"].pop(gate)
        accepted.append(gate)
    require(review["full_acceptance"] is False, "final component joins cannot override incomplete acceptance")
    if accepted:
        previous = review.get("final_closed_evidence_integration", {}).get("gates", [])
        review["final_closed_evidence_integration"] = {"gates": sorted([*previous, *accepted]), "native_starts": 0, "browser_starts": 0, "closed_semantic_sample_replays": 0, "full_acceptance": False}
