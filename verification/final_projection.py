"""Unexecuted saved-evidence coordinator draft, not an accepted entry point.

Only the separate unexecuted admission-entry draft prepares CLI dispatch here.
Execution requires fresh direct human authority and a separately admitted scope.
The accepted full_bundle inspection and domain readers retain their contracts.
"""

import hashlib
import json
from pathlib import Path

from verification.bundle import Bundle
from verification.final_audit_bundle import validate_projection_audit
from verification.final_audit_bundle import verify_or_unverified as verify_final_audit
from verification.final_audit_trust import load_external_trust
from verification.final_core_bundle import DRIVERS as CORE_DRIVERS
from verification.final_core_bundle import verify as verify_closed_core
from verification.final_evidence_bundle import DRIVERS as EVIDENCE_DRIVERS
from verification.final_evidence_bundle import ENGINE, NETWORK
from verification.final_evidence_bundle import verify as verify_closed_evidence
from verification.final_gate_decisions import DRIVERS as NONPASSING_DRIVERS
from verification.final_gate_decisions import blocked_release, verify_nonpassing_gate
from verification.final_semantic_bundle import DRIVER as SEMANTIC_DRIVER
from verification.final_semantic_bundle import verify_or_unverified
from verification.full_bundle import GATES, inspect
from verification.source import require


CLOSED_GATES = {f"G{i:02d}" for i in range(1, 8)} | {"G09", "G11", "G12", "G13"}
CLOSED_DRIVERS = {**CORE_DRIVERS, **EVIDENCE_DRIVERS}


def normalized_closed_result(result, gate, expected_commit):
    require(result["gate"] == gate and result["full_gate"] is True
            and result["status"] == "passed_final_closed_evidence_adapter"
            and result["coordinator_source_commit"] == expected_commit
            and result["engine_sha256"] == ENGINE and result["network_sha256"] == NETWORK
            and result["full_acceptance"] is False,
            "final closed result is stale, mismatched or only a component")
    raw = json.dumps(result, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    return {"gate": gate, "source_commit": expected_commit,
            "engine_sha256": ENGINE, "network_sha256": NETWORK,
            "classification": "verified", "requirement_satisfied": True,
            "full_gate": True, "full_acceptance": False,
            "actual_adapter_result_sha256": hashlib.sha256(raw).hexdigest()}


def project(decisions, audit, expected_commit, audit_trust=None):
    """Internal derived projection of actual same-invocation adapter outputs."""
    release = blocked_release(decisions, expected_commit)
    validate_projection_audit(audit, expected_commit, audit_trust)
    prior_pass = all(d["requirement_satisfied"] for d in decisions.values())
    full_acceptance = prior_pass and audit["requirement_satisfied"]
    release.update(independent_final_audit=audit,
                   requirement_satisfied=full_acceptance,
                   full_gate=full_acceptance,
                   full_acceptance=full_acceptance,
                   release_authorized=full_acceptance,
                   classification="verified" if full_acceptance else "blocked")
    inventory = {**decisions, "G16": release}
    require(set(inventory) == GATES and len(inventory) == 16,
            "complete decision projection lost or duplicated a gate")
    counts = {}
    for gate, row in inventory.items():
        require(row["gate"] == gate and row["source_commit"] == expected_commit,
                "decision projection source or gate differs")
        counts[row["classification"]] = counts.get(row["classification"], 0) + 1
    return {"status": "passed" if full_acceptance else "incomplete",
            "profile": "full", "source_commit": expected_commit,
            "engine_sha256": ENGINE, "network_sha256": NETWORK,
            "gate_decisions": inventory, "decision_counts": counts,
            "decision_inventory_complete": True, "full_acceptance": full_acceptance,
            "exit_code": 0 if full_acceptance else 2,
            "new_native_browser_compiler_training_inference_or_game_starts": 0,
            "closed_semantic_sample_or_control_replays": 0,
            "original_compiler_runtime_closure": False}


def verify(root, checkout, expected_commit, expected_inputs_sha256, maximum_seconds=60,
           *, audit_trust_path=None, expected_audit_trust_sha256=None):
    """Prospective read-only full projection, prohibited until fresh admission."""
    require(expected_inputs_sha256 is not None, "external full-input identity required")
    from tools.heuristic_study import avoid_decisive_matches

    avoid_decisive_matches(Path(checkout) / "runs")
    with Bundle(root, maximum_seconds) as bundle:
        admission = inspect(bundle, checkout, expected_commit, expected_inputs_sha256)
        audit_trust = load_external_trust(
            checkout, bundle.root, audit_trust_path, expected_audit_trust_sha256,
            expected_commit, hashlib.sha256(bundle.bytes("SOURCE_INPUTS.json")).hexdigest())
        inputs = bundle.json("FULL_INPUTS.json")
        decisions, actual = {}, {}
        for gate in sorted(CLOSED_GATES):
            require(inputs["domains"][gate]["driver"] == CLOSED_DRIVERS[gate],
                    "projection cannot dispatch a legacy sample replay")
            reader = verify_closed_evidence if gate in {"G11", "G12"} else verify_closed_core
            result = reader(bundle, inputs, checkout, expected_commit, gate)
            decisions[gate] = normalized_closed_result(result, gate, expected_commit)
            actual[gate] = result
        for gate in sorted(NONPASSING_DRIVERS):
            decisions[gate] = verify_nonpassing_gate(bundle, inputs, checkout, expected_commit, gate)
        require(inputs["domains"]["G14"]["driver"] == SEMANTIC_DRIVER,
                "projection cannot rerun a historical semantic audit")
        decisions["G14"] = verify_or_unverified(bundle, inputs, checkout, expected_commit)
        audit = verify_final_audit(bundle, inputs, checkout, expected_commit, audit_trust)
        report = project(decisions, audit, expected_commit, audit_trust)
        report["inputs_sha256"] = expected_inputs_sha256
        report["verified_relationships"] = admission["verified_relationships"]
        report["actual_closed_adapter_results"] = actual
        report["unverified_gates"] = {
            gate: row["reason"] for gate, row in decisions.items()
            if row["classification"] == "unverified"
        }
        return report
