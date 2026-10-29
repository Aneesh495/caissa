"""Unexecuted new policy controls for a future finite metadata-only owner.

These in-memory cases are not full-entry integration, real gate evidence or a
closed semantic sample. This module has no CLI and runs no controls on import.
An admitted owner must call run_controls exactly once before trust-root activation.
"""

import copy

from verification import final_audit_bundle as audit_reader
from verification import final_semantic_bundle as semantic_reader
from verification.final_evidence_bundle import ENGINE, NETWORK
from verification.final_projection import normalized_closed_result, project
from verification.source import require


SOURCE = "1" * 40


class NoArtifactRead:
    def __getattr__(self, name):
        raise AssertionError("missing-root policy unexpectedly read an artifact: " + name)


def fixtures():
    # Synthetic adapter-result shapes exercise policy only. They are never
    # submitted to Bundle admission or described as independently accepted gates.
    result = {"gate": "G01", "status": "passed_final_closed_evidence_adapter",
              "coordinator_source_commit": SOURCE, "engine_sha256": ENGINE,
              "network_sha256": NETWORK, "full_gate": True, "full_acceptance": False}
    classifications = {"G08": "failed_requirement", "G10": "incomplete",
                       "G14": "unverified", "G15": "unavailable_inputs"}
    decisions = {}
    for i in range(1, 16):
        gate = f"G{i:02d}"
        category = classifications.get(gate, "verified")
        decisions[gate] = {"gate": gate, "source_commit": SOURCE,
                           "engine_sha256": ENGINE, "network_sha256": NETWORK,
                           "classification": category,
                           "requirement_satisfied": category == "verified"}
    domain = {"source_commit": SOURCE, "driver": semantic_reader.DRIVER,
              "engine_sha256": ENGINE, "network_sha256": NETWORK, "artifacts": []}
    inputs = {"engine": {"sha256": ENGINE}, "network": {"artifact": {"sha256": NETWORK}},
              "domains": {"G14": domain,
                          "G16": {**domain, "driver": audit_reader.DRIVER}}}
    return {"result": result, "decisions": decisions, "inputs": inputs,
            "audit": audit_reader.unverified(SOURCE)}


def run_controls():
    require(semantic_reader.ACCEPTED_JOIN is None,
            "these new controls require the admitted pre-activation source state")
    cases = []

    def reject(name, mutate, check):
        f = fixtures()
        mutate(f)
        try:
            check(f)
        except (ValueError, KeyError, TypeError) as error:
            cases.append({"case": name, "rejected": True, "reason": str(error)})
        else:
            raise ValueError("new projection policy forgery accepted: " + name)

    normalize = lambda f: normalized_closed_result(f["result"], "G01", SOURCE)
    projection = lambda f: project(f["decisions"], f["audit"], SOURCE)
    g14 = lambda f: semantic_reader.verify_or_unverified(NoArtifactRead(), f["inputs"], None, SOURCE)
    g16 = lambda f: audit_reader.verify_or_unverified(NoArtifactRead(), f["inputs"], None, SOURCE)

    for name, change in [
        ("component_cannot_normalize_as_full_gate", {"full_gate": False}),
        ("integer_cannot_replace_true_gate_flag", {"full_gate": 1}),
        ("stale_normalized_result_source", {"coordinator_source_commit": "2" * 40}),
        ("wrong_normalized_result_engine", {"engine_sha256": "0" * 64}),
        ("wrong_normalized_result_network", {"network_sha256": "0" * 64}),
        ("closed_result_cannot_claim_project_acceptance", {"full_acceptance": True}),
    ]:
        reject(name, lambda f, change=change: f["result"].update(change), normalize)

    for name, mutate in [
        ("missing_prior_gate", lambda f: f["decisions"].pop("G08")),
        ("unknown_extra_prior_gate", lambda f: f["decisions"].update(G99=f["decisions"]["G01"])),
        ("wrong_prior_gate_identity", lambda f: f["decisions"]["G08"].update(gate="G09")),
        ("stale_prior_source", lambda f: f["decisions"]["G08"].update(source_commit="2" * 40)),
        ("wrong_prior_saved_actor", lambda f: f["decisions"]["G08"].update(engine_sha256="0" * 64)),
        ("integer_cannot_replace_requirement_bool", lambda f: f["decisions"]["G08"].update(requirement_satisfied=1)),
        ("failed_category_cannot_claim_satisfied", lambda f: f["decisions"]["G08"].update(requirement_satisfied=True)),
    ]:
        reject(name, mutate, projection)

    reject("G14_unaccepted_artifact", lambda f: f["inputs"]["domains"]["G14"].update(
        artifacts=[{"path": "invented.json", "sha256": "0" * 64}]), g14)
    reject("G14_caller_pass_flag", lambda f: f["inputs"]["domains"]["G14"].update(
        full_gate=True), g14)
    reject("G14_legacy_replay_driver", lambda f: f["inputs"]["domains"]["G14"].update(
        driver="semantic-audit-v1"), g14)
    reject("audit_artifact_without_accepted_roots", lambda f: f["inputs"]["domains"]["G16"].update(
        artifacts=[{"path": "invented-audit.json", "sha256": "0" * 64}]), g16)
    reject("audit_caller_pass_flag", lambda f: f["inputs"]["domains"]["G16"].update(
        full_acceptance=True), g16)
    reject("audit_stale_source", lambda f: f["inputs"]["domains"]["G16"].update(
        source_commit="2" * 40), g16)
    reject("invented_verified_audit_receipt", lambda f: f["audit"].update(
        classification="verified", requirement_satisfied=True, full_gate=True,
        accepted_audit_sha256="0" * 64), projection)
    reject("audit_projection_wrong_network", lambda f: f["audit"].update(
        network_sha256="0" * 64), projection)
    reject("unverified_audit_cannot_enable_acceptance", lambda f: f["audit"].update(
        requirement_satisfied=True, full_gate=True), projection)

    f = fixtures()
    original = copy.deepcopy(f)
    report = projection(f)
    require(report["decision_inventory_complete"] is True
            and report["full_acceptance"] is False and report["exit_code"] == 2
            and report["decision_counts"] == {"verified": 11, "failed_requirement": 1,
                                               "incomplete": 1, "unverified": 1,
                                               "unavailable_inputs": 1, "blocked": 1}
            and report["gate_decisions"]["G16"]["release_authorized"] is False
            and f == original,
            "synthetic projection lost a nonpassing category or mutated its inputs")
    cases.append({"case": "all_six_categories_preserved_without_input_mutation",
                  "synthetic_policy_check": True, "full_acceptance": False})
    return {"status": "passed_new_synthetic_projection_policy_controls",
            "cases": cases, "controls": len(cases), "real_domain_results_checked": 0,
            "actual_full_entry_starts": 0, "full_R12_complete": False,
            "full_acceptance": False}
