"""Unexecuted draft for the frozen nonpassing final gate decisions.

This module is deliberately absent from full_bundle dispatch. A future admitted
entry must verify the current source inventory before calling these readers.
Reading saved evidence here never authorizes a new experiment or a release.
"""

import hashlib
import re

from verification.bundle import strict_json
from verification.final_core_bundle import learning
from verification.final_evidence_bundle import ENGINE, NETWORK, boundary, source_bytes
from verification.source import relative_path, require


POLICY = "config/final-gate-decisions-v1.json"
POLICY_SHA256 = "ff095700d8e720d05e8709284fe482809e64c7603be2d333aa4bfd5af1299cc5"
CHECKPOINT = "c76d8e9ef0f2255531bc9085f5d0330a7a4152cf9b21a65ff8aee740ab8b2005"
MODEL = "92d62149d3a4de184ad93b9f5f04f77e38386992d04d02bd824b33cf3e5241bd"
BOUNDARY = "results/final-core-runtime-join-2026-10-28/BOUNDARY.json"
NEURAL = "results/neural-v4-failure-2026-10-26/"
PARALLEL = "runs/full-parallel-strength-v1/"
FIFTH = PARALLEL + "attempts/attempt-005/"
PARALLEL_WORK = "work/parallel-storage-2026-10-28/"
PARALLEL_SCOPE = PARALLEL_WORK + "PARALLEL_CONTINUATION_5_SCOPE.json"
PARALLEL_CLOSED = ".agent-local/PARALLEL_CONTINUATION_5_CLOSED.json"
LINEAGE = "work/final-data-learning-lineage-1-2026-10-29/"
ATTRIBUTION = "results/build-attribution-2026-10-27/RESULT.json"
NEURAL_STAGE = "runs/full-neural-strength-v4-wall-recovery-v1/attempts/attempt-001/independent-neural.json"
PROTOCOL_SHA256 = "a8623bf2d59561d434546ad612c939f994a4e699b1c61f4eba5b3114f26528dd"
MATRIX_SHA256 = "5b405adcb7edbdc4bbae410612c7867879a83f73e635ed5ca29c26eeee072f48"
DRIVERS = {
    "G08": "final-failed-neural-decision-v1",
    "G10": "final-incomplete-matrix-decision-v1",
    "G15": "final-unavailable-reproduction-decision-v1",
}
COMPARISONS = (
    ("threads-2-ms-100", 2, 100),
    ("threads-2-ms-400", 2, 400),
    ("threads-4-ms-100", 4, 100),
    ("threads-4-ms-400", 4, 400),
    ("threads-8-ms-100", 8, 100),
)


class DecisionRecords:
    """Read only the fixed small metadata inventory, through Bundle checks."""

    def __init__(self, bundle, domain, gate, checkout):
        policy_raw = source_bytes(checkout, POLICY)
        require(hashlib.sha256(policy_raw).hexdigest() == POLICY_SHA256,
                "frozen decision policy changed")
        policy = strict_json(policy_raw)
        require(policy["schema"] == "caissa-frozen-nonpassing-decision-policy-v1"
                and policy["execution_authority"] is False,
                "decision policy cannot authorize execution")
        descriptor = bundle.json(bundle.reference(domain["final_decision_evidence"]))
        require(set(descriptor) == {"schema", "gate", "records"}
                and descriptor["schema"] == "caissa-frozen-nonpassing-records-v1"
                and descriptor["gate"] == gate,
                "nonpassing decision descriptor differs")
        self.records = descriptor["records"]
        self.pins = policy["gates"][gate]["records"]
        require(isinstance(self.records, dict) and set(self.records) == set(self.pins)
                and 0 < len(self.records) <= 128,
                "nonpassing decision metadata inventory differs")
        self.bundle, self.cache = bundle, {}
        for name, reference in self.records.items():
            relative_path(name)
            bundle.reference(reference)
        declared = {bundle.reference(x) for x in domain["artifacts"]}
        require(declared == {domain["final_decision_evidence"]["path"],
                             *(x["path"] for x in self.records.values())},
                "nonpassing decision evidence undeclared or excessive")
        require(sum(pin["bytes"] for pin in self.pins.values()) <= 4 * 1024**2,
                "nonpassing metadata budget exceeded")
        for name in self.pins:
            self.raw(name)

    def raw(self, name):
        require(name in self.records, "required nonpassing evidence missing: " + name)
        if name not in self.cache:
            raw = self.bundle.bytes(self.bundle.reference(self.records[name]), 4 * 1024**2)
            pin = self.pins[name]
            require(len(raw) == pin["bytes"]
                    and hashlib.sha256(raw).hexdigest() == pin["sha256"],
                    "fixed original nonpassing evidence changed: " + name)
            self.cache[name] = raw
        return self.cache[name]

    def sha(self, name):
        return hashlib.sha256(self.raw(name)).hexdigest()

    def doc(self, name):
        return strict_json(self.raw(name))


def neural_failure(records):
    original, recovery = (records.doc(NEURAL + label + "-SCOPE.json")
                          for label in ("original", "recovery"))
    protocol = records.doc("config/protocol-v4.json")
    matches, actor = protocol["matches"], protocol["strength_actor"]
    require(records.sha("config/protocol-v4.json") == PROTOCOL_SHA256
            and actor["engine_sha256"] == ENGINE and actor["network_sha256"] == NETWORK
            and actor["checkpoint_sha256"] == CHECKPOINT
            and actor["original_model_campaign_sha256"] == MODEL,
            "original neural protocol or actor differs")
    for scope in (original, recovery):
        b = scope["bindings"]
        require(b["source_commit"] == "9f3ac86ca38eb28b357ad7ef146f1af4bfb96021"
                and b["engine_sha256"] == ENGINE and b["network_sha256"] == NETWORK
                and b["protocol_sha256"] == PROTOCOL_SHA256,
                "failed neural scope identities differ")
    require(original["bindings"]["original_model_campaign_sha256"] == MODEL,
            "original neural selection campaign differs")
    b = recovery["bindings"]
    for key, name in (("original_scope_sha256", "original-SCOPE.json"),
                      ("original_failure_sha256", "original-FAILED.json"),
                      ("original_usage_sha256", "original-ACTIVE_USAGE.json")):
        require(b[key] == records.sha(NEURAL + name), "neural recovery parent differs")
    old_usage = records.doc(NEURAL + "original-ACTIVE_USAGE.json")
    usage = records.doc(NEURAL + "recovery-ACTIVE_USAGE.json")
    require(old_usage["closed"] is True and usage["closed"] is True
            and b["original_active_seconds"] == old_usage["active_seconds"]
            and 0 < usage["combined_active_seconds"] <= original["maximum_active_seconds"],
            "failed neural usage was reopened or reset")
    first, second = (records.doc(NEURAL + label) for label in
                     ("original-FAILED.json", "recovery-FAILED-001.json"))
    require(first["reason"] == "stage play-neural failed: stage-timeout (exit -15)"
            and second["reason"] == "stage independent-neural failed: nonzero-exit (exit 1)"
            and first["full_acceptance"] is second["full_acceptance"] is False,
            "original failed neural outcomes changed")
    receipt = records.doc(NEURAL_STAGE)
    require(receipt["event"] == "stage-finished" and receipt["stage"] == "independent-neural"
            and type(receipt["exit"]) is int and receipt["exit"] == 1
            and receipt["reason"] == "nonzero-exit" and receipt["cleanup_warnings"] == []
            and receipt["discarded_output_bytes"] == 0,
            "original independent neural failure differs")
    handoff, summary = records.doc(NEURAL + "HANDOFF.json"), records.doc(NEURAL + "SUMMARY.json")
    require(handoff["recovery_failure_sha256"] == records.sha(NEURAL + "recovery-FAILED-001.json")
            and handoff["combined_active_seconds"] == usage["combined_active_seconds"]
            and handoff["original_failure_preserved"] is handoff["no_neural_rerun"] is True,
            "neural failure handoff differs")
    require(matches["neural_pairs"] == 2000 and matches["maximum_plies"] == 512
            and matches["minimum_neural_gain_elo"] == 50
            and matches["minimum_neural_lower_elo_exclusive"] == 0
            and matches["confidence"] == 0.95,
            "original neural requirement weakened")
    require(handoff["neural_game_records"] == 4000 and handoff["completed_games"] == 3997
            and [(x["pair"], x["reverse"], x["termination"], x["plies"])
                 for x in handoff["unfinished"]]
            == [(1242, 1, "ply-limit", 512), (1500, 1, "ply-limit", 512),
                (1684, 0, "ply-limit", 512)]
            and (summary["games"], summary["wins"], summary["draws"], summary["losses"],
                 summary["unfinished_games"], summary["complete_pairs"])
            == (3997, 1430, 409, 2158, 3, 1997)
            and summary["complete_sample"] is False
            and handoff["neural_full_gate"] is handoff["neural_strength_certified"] is False,
            "unfinished original neural outcomes were promoted or removed")
    require(summary["elo_difference"] < matches["minimum_neural_gain_elo"]
            and summary["elo_95"][0] <= matches["minimum_neural_lower_elo_exclusive"],
            "retained finished-subset statistic contradicts the failed endpoint")
    return {
        "classification": "failed_requirement", "requirement_satisfied": False,
        "attempts": 4000, "finished": 3997, "unfinished": 3,
        "gain_requirement_elo": 50, "positive_lower_endpoint_required": True,
        "finished_subset_relative_elo": summary["elo_difference"],
        "finished_subset_relative_elo_95": summary["elo_95"],
        "finished_subset_is_accepted_full_sample": False,
        "original_independent_exit": receipt["exit"],
        "original_independent_log_sha256_in_receipt": receipt["log_sha256"],
        "original_independent_log_body_recovered": False,
        "full_raw_game_replay_performed": False, "absolute_or_default_rating": None,
    }


def accepted_comparison(records, comparison):
    """Follow the exact retained first-comparison reuse without a new run."""
    label = "independent-" + comparison
    receipt_name = FIFTH + label + ".json"
    result_name = FIFTH + label + ".log"
    seen = set()
    for _ in range(5):
        require(receipt_name not in seen, "comparison reuse cycle")
        seen.add(receipt_name)
        receipt = records.doc(receipt_name)
        require(receipt["stage"] == label and type(receipt["exit"]) is int
                and receipt["exit"] == 0, "accepted comparison exit differs")
        if receipt["event"] == "stage-finished":
            log_name = receipt_name[:-5] + ".log"
            require(receipt["reason"] == "completed" and receipt["cleanup_warnings"] == []
                    and receipt["discarded_output_bytes"] == 0
                    and records.sha(log_name) == receipt["log_sha256"]
                    and records.sha(log_name) == records.sha(result_name),
                    "actual independent comparison log or cleanup differs")
            return records.doc(result_name)
        require(receipt["event"] == "stage-reused-without-execution"
                and receipt["reason"] == "original completed stage retained",
                "unsupported comparison reuse receipt")
        retained = receipt["original_log"]
        require(re.fullmatch(r"attempts/attempt-00[1-4]/" + re.escape(label) + r"\.log", retained)
                and records.sha(PARALLEL + retained) == receipt["sha256"]
                and receipt["sha256"] == records.sha(result_name),
                "comparison reuse escapes or changes the original result")
        receipt_name = PARALLEL + retained[:-4] + ".json"
    raise ValueError("comparison reuse chain excessive")


def incomplete_matrix(records):
    scope, closed = records.doc(PARALLEL_SCOPE), records.doc(PARALLEL_CLOSED)
    usage, writes = records.doc(PARALLEL + "ACTIVE_USAGE.json"), records.doc(PARALLEL_WORK + "WRITE_USAGE_5.json")
    profile = records.doc("config/systems-parallel-v1.json")
    require(records.sha("config/systems-parallel-v1.json") == MATRIX_SHA256
            and profile["base_protocol_sha256"] == PROTOCOL_SHA256
            and scope["actual_engine_sha256"] == ENGINE and scope["actual_network_sha256"] == NETWORK,
            "frozen matrix protocol or actor differs")
    require(usage["closed"] is writes["closed"] is True and writes.get("failure") is None
            and writes["scope_sha256"] == records.sha(PARALLEL_SCOPE)
            and scope["maximum_active_seconds"] == usage["maximum_active_seconds"] == 28800
            and usage["active_seconds"] == closed["actual_active_seconds"] == 28800.50948912598
            and scope["extra_active_seconds"] == closed["active_seconds_added"] == 0
            and closed["replacement_owner_admitted"] is False,
            "closed matrix limits were reopened, reset or hidden")
    require((closed["recorded_attempts"], closed["recorded_pairs"], closed["scheduled_attempts"],
             closed["independently_checked_comparisons"]) == (1110, 555, 1200, 5)
            and closed["original_game_records_preserved"] is True
            and closed["full_G10_certified"] is closed["full_acceptance"] is False,
            "incomplete matrix counts or outcome differ")
    progress, last = records.doc(FIFTH + "PROGRESS.json"), records.doc(FIFTH + "play-threads-8-ms-400.json")
    require(progress["phase"] == "play-threads-8-ms-400"
            and progress["stopping_reason"] == closed["stage_reason"] == last["reason"] == "campaign-timeout"
            and type(last["exit"]) is int and last["exit"] == closed["stage_exit"] == -15
            and last["cleanup_warnings"] == [] and last["discarded_output_bytes"] == 0
            and records.sha(FIFTH + "play-threads-8-ms-400.log") == last["log_sha256"],
            "actual incomplete final comparison changed")
    require([(x["id"], x["threads"], x["budget"], x["pairs"]) for x in profile["comparisons"]]
            == [(name, threads, ms, 100) for name, threads, ms in COMPARISONS]
            + [("threads-8-ms-400", 8, 400, 100)], "frozen six-comparison schedule differs")
    reused = records.doc(FIFTH + "independent-threads-2-ms-100.json")
    admitted_reuse = scope["reused_stages"]["independent-threads-2-ms-100"]
    require(reused["original_log"] == admitted_reuse["log"]
            and reused["sha256"] == admitted_reuse["sha256"],
            "first comparison differs from the admitted original reuse")
    accepted = []
    for name, threads, _ in COMPARISONS:
        result = accepted_comparison(records, name)
        stats, raw = result["statistics"], result["raw_journals"]
        require(result["status"] == "passed" and result["comparison"] == name
                and result["profile_sha256"] == MATRIX_SHA256 and result["kind"] == "parallel"
                and result["full_G10_certified"] is result["full_acceptance"] is False
                and result["absolute_elo"] is None and stats["games"] == 200
                and stats["unfinished_games"] == 0 and stats["complete_pairs"] == 100
                and raw["status"] == "passed" and raw["pairs"] == 100
                and raw["game_journals"] == raw["pgn_files"] == 200,
                "accepted comparison evidence incomplete or promoted to full matrix")
        identities = [result[side] for side in ("candidate_identity", "opponent_identity")]
        require({k: v for k, v in identities[0]["options"].items() if k != "Threads"}
                == {k: v for k, v in identities[1]["options"].items() if k != "Threads"},
                "self-comparison changed options beyond thread count")
        for identity, thread_count in zip(identities, (threads, 1), strict=True):
            options = identity["options"]
            require(identity["executable"] == ENGINE and identity["network_sha256"] == NETWORK
                    and options["Threads"] == thread_count and options["Hash"] == 16
                    and options["Neural Weight"] == 10 and options["Use Neural"] is True
                    and options["Lazy Neural"] is True and options["Evaluation Cache"] is True
                    and options["Tactical Generation"] is True,
                    "accepted comparison saved actor or applied options differ")
        accepted.append({"comparison": name, "independent_result_sha256": records.sha(FIFTH + "independent-" + name + ".log")})
    return {
        "classification": "incomplete", "requirement_satisfied": False,
        "recorded_attempts": 1110, "scheduled_attempts": 1200, "recorded_pairs": 555,
        "counts_source": "retained closed owner census, no new journal replay",
        "accepted_comparisons": accepted, "incomplete_comparison": "threads-8-ms-400",
        "original_active_seconds": usage["active_seconds"], "original_active_cap": 28800,
        "shutdown_overrun_preserved": True, "new_games_or_active_allowance": 0,
        "full_matrix_certified": False, "aggregate_or_absolute_rating": None,
    }


def unavailable_reproduction(records, checkout):
    # Reuse the accepted metadata relationship reader, never its producer main,
    # training pipeline, array readers or any closed semantic sample.
    joined = learning(records, checkout)
    availability = records.doc(LINEAGE + "AVAILABILITY.json")
    attribution = records.doc(ATTRIBUTION)
    for key in ("saved_original_image_replaced", "saved_original_compiler_invocation_proven",
                "runtime_dynamic_dependency_closure_proven", "complete_platform_input_transport",
                "full_G15_certified", "full_acceptance"):
        require(attribution[key] is False, "later attribution component promoted original reproduction")
    require(attribution["failed_first_run"] == 40426236191
            and attribution["passed_second_run"] == 40426808520
            and attribution["source_commit"] == "169222a3f8e0960e667d7e0fd458744de8b783c8"
            and set(attribution["new_attribution_image_sha256"]) == {"linux", "macos"}
            and all(digest != ENGINE for digest in attribution["new_attribution_image_sha256"].values()),
            "later attribution image substituted for original saved actor")
    require(availability["selected_alternate"]["bytes"] == 9518976
            and joined["retained_validation_rows"] == 8192,
            "retained subset and full historical inputs conflated")
    return {
        "classification": "unavailable_inputs", "requirement_satisfied": False,
        "original_full_arrays_unavailable": 6, "original_checkpoint_paths_unavailable": 240,
        "original_audit_catalogs_unavailable": 3, "complete_retired_corpus_leaf_inventory": False,
        "retained_selected_checkpoint_bytes": 9518976, "retained_validation_rows": 8192,
        "original_saved_actor_compiler_invocation": "unverified",
        "original_saved_actor_runtime_closure": "unverified",
        "complete_platform_input_transport": False, "full_raw_reproduction": False,
        "later_attribution_report_sha256": records.sha(ATTRIBUTION),
        "later_attribution_component_reexecuted": False,
    }


def verify_nonpassing_gate(bundle, inputs, checkout, expected_commit, gate):
    """Prospective hook, requiring an outer admitted source-verified full entry."""
    require(gate in DRIVERS, "unsupported frozen nonpassing gate")
    domain = inputs["domains"][gate]
    require(domain["driver"] == DRIVERS[gate] and domain["source_commit"] == expected_commit
            and domain["engine_sha256"] == inputs["engine"]["sha256"] == ENGINE
            and domain["network_sha256"] == inputs["network"]["artifact"]["sha256"] == NETWORK,
            "nonpassing decision source, driver or deployment differs")
    records = DecisionRecords(bundle, domain, gate, checkout)
    deployment = records.doc(BOUNDARY)
    require(deployment["checkpoint_sha256"] == CHECKPOINT,
            "nonpassing decision selected checkpoint differs")
    boundary(checkout, deployment)
    details = (neural_failure(records) if gate == "G08" else incomplete_matrix(records)
               if gate == "G10" else unavailable_reproduction(records, checkout))
    return {"gate": gate, "source_commit": expected_commit,
            "engine_sha256": ENGINE, "network_sha256": NETWORK,
            "evidence_relationships_checked": True, "full_gate": False,
            "full_acceptance": False, "metadata_records": len(records.records),
            "evidence_inventory_sha256": hashlib.sha256(
                source_bytes(checkout, POLICY)).hexdigest(), **details}


def blocked_release(prior_decisions, expected_commit):
    """Fail closed until a separately accepted final audit adapter exists.

    This is an internal projection helper, not an evidence admission interface.
    Only actual adapter results from the same full-entry invocation may reach it.
    It cannot produce an audit pass or turn caller all-green flags into release.
    """
    expected = {f"G{i:02d}" for i in range(1, 16)}
    require(isinstance(prior_decisions, dict) and set(prior_decisions) == expected,
            "release projection requires exactly G01 through G15")
    blockers = {}
    for gate in sorted(expected):
        decision = prior_decisions[gate]
        require(decision["gate"] == gate and decision["source_commit"] == expected_commit
                and decision["engine_sha256"] == ENGINE and decision["network_sha256"] == NETWORK
                and type(decision["requirement_satisfied"]) is bool,
                "release projection contains stale or mismatched decisions")
        require(decision["classification"] in {
            "verified", "failed_requirement", "incomplete", "unavailable_inputs", "unverified"
        } and decision["requirement_satisfied"] == (decision["classification"] == "verified"),
                "release projection classification contradicts its requirement")
        if not decision["requirement_satisfied"]:
            blockers[gate] = decision["classification"]
    return {"gate": "G16", "source_commit": expected_commit,
            "engine_sha256": ENGINE, "network_sha256": NETWORK,
            "classification": "blocked", "requirement_satisfied": False,
            "prior_gate_blockers": blockers, "independent_final_audit": "unverified",
            "full_gate": False, "full_acceptance": False,
            "release_authorized": False}
