"""Unexecuted interface for an independently accepted final audit component.

No such final audit is accepted. Missing trust roots cannot be supplied by a
bundle or caller. The future accepted path requires real independent process,
source, input and closure evidence; it does not close other release gates.
"""

import hashlib

from verification.bundle import strict_json
from verification.final_evidence_bundle import ENGINE, NETWORK, owner, source_bytes
from verification.source import relative_path, require


DRIVER = "final-release-audit-v1"
ACCEPTED_AUDIT = None
AREAS = {
    "product_source_inventory", "dependency_attribution", "source_similarity",
    "provenance_limitations", "secret_exposure_review", "release_claim_consistency",
}
EMPTY_KEYS = {"source_commit", "driver", "artifacts", "engine_sha256", "network_sha256"}


def unverified(expected_commit):
    return {"gate": "G16-audit", "source_commit": expected_commit,
            "engine_sha256": ENGINE, "network_sha256": NETWORK,
            "classification": "unverified", "requirement_satisfied": False,
            "full_gate": False, "full_acceptance": False,
            "accepted_audit_sha256": None,
            "reason": "independent final source/provenance/security audit not accepted"}


def validate_projection_audit(audit, expected_commit):
    """Internal consistency check, never a replacement for artifact admission."""
    require(audit["gate"] == "G16-audit" and audit["source_commit"] == expected_commit
            and audit["engine_sha256"] == ENGINE and audit["network_sha256"] == NETWORK
            and type(audit["requirement_satisfied"]) is bool
            and type(audit["full_gate"]) is bool and audit["full_acceptance"] is False,
            "final audit projection identity or types differ")
    if audit["classification"] == "unverified":
        require(audit["requirement_satisfied"] is audit["full_gate"] is False
                and audit["accepted_audit_sha256"] is None,
                "unverified audit promoted by a caller flag")
        return
    require(audit["classification"] == "verified" and ACCEPTED_AUDIT is not None
            and audit["accepted_audit_sha256"] == ACCEPTED_AUDIT["result_sha256"]
            and audit["requirement_satisfied"] is audit["full_gate"] is True,
            "no trusted independently accepted final audit result")


class AuditRecords:
    def __init__(self, bundle, domain):
        require(ACCEPTED_AUDIT is not None, "final audit trust roots absent")
        descriptor = bundle.json(bundle.reference(domain["final_audit_evidence"]))
        require(set(descriptor) == {"schema", "gate", "records"}
                and descriptor["schema"] == "caissa-final-independent-audit-records-v1"
                and descriptor["gate"] == "G16-audit", "final audit descriptor differs")
        self.records = descriptor["records"]
        require(isinstance(self.records, dict) and 0 < len(self.records) <= 512,
                "final audit metadata inventory empty or excessive")
        for name, reference in self.records.items():
            relative_path(name)
            bundle.reference(reference)
        declared = {bundle.reference(x) for x in domain["artifacts"]}
        require(declared == {domain["final_audit_evidence"]["path"],
                             *(x["path"] for x in self.records.values())},
                "final audit records undeclared or excessive")
        self.bundle, self.cache, self.total = bundle, {}, 0
        work = ACCEPTED_AUDIT["work"]
        require(work.endswith("/") and relative_path(work[:-1]), "invalid final audit root")
        for name, digest in (("SCOPE.json", ACCEPTED_AUDIT["scope_sha256"]),
                             ("AUDIT.json", ACCEPTED_AUDIT["result_sha256"])):
            require(self.sha(work + name) == digest, "trusted final audit scope/result changed")

    def raw(self, name):
        require(name in self.records, "required final audit record missing: " + name)
        if name not in self.cache:
            raw = self.bundle.bytes(self.bundle.reference(self.records[name]), 8 * 1024**2)
            self.total += len(raw)
            require(self.total <= 32 * 1024**2, "final audit metadata budget exceeded")
            self.cache[name] = raw
        return self.cache[name]

    def sha(self, name):
        return hashlib.sha256(self.raw(name)).hexdigest()

    def doc(self, name):
        return strict_json(self.raw(name))


def verify_or_unverified(bundle, inputs, checkout, expected_commit):
    domain = inputs["domains"]["G16"]
    require(domain["source_commit"] == expected_commit and domain["driver"] == DRIVER
            and domain["engine_sha256"] == inputs["engine"]["sha256"] == ENGINE
            and domain["network_sha256"] == inputs["network"]["artifact"]["sha256"] == NETWORK,
            "final audit driver or deployment differs")
    if domain["artifacts"] == []:
        require(set(domain) == EMPTY_KEYS, "empty audit declaration contains unverified pass fields")
        return unverified(expected_commit)
    require(ACCEPTED_AUDIT is not None, "offered audit artifacts have no accepted trust roots")
    records = AuditRecords(bundle, domain)
    work = ACCEPTED_AUDIT["work"]
    scope, result = records.doc(work + "SCOPE.json"), records.doc(work + "AUDIT.json")
    closed = owner(records, work, ACCEPTED_AUDIT["scope_sha256"])
    require(closed["owned_group_absent_after_reap"] is True,
            "final audit owner group remains present")
    ledger = records.doc(work + "METADATA_USAGE.json")
    require(ledger["closed"] is True and ledger["failure"] is None
            and ledger["scope_sha256"] == ACCEPTED_AUDIT["scope_sha256"]
            and ledger["native_starts"] == 0 and ledger["child_starts"] == 1,
            "final audit ledger open, failed or actor starts differ")
    require(records.doc(work + "GROUPS.json")
            == [{"stage": "independent-audit", "group_absent_after_reap": True}],
            "independent audit process group did not close")
    stage = records.doc(work + "independent-audit.json")
    require(type(stage["exit"]) is int and stage["exit"] == 0
            and stage["stage"] == "independent-audit" and stage["reason"] == "completed"
            and stage["command"] == scope["independent_command"]
            and stage["cleanup_warnings"] == [] and stage["discarded_output_bytes"] == 0
            and stage["log_sha256"] == records.sha(work + "independent-audit.log")
            and records.doc(work + "independent-audit.log") == result,
            "actual independent audit exit/output differs")
    summary = records.doc(work + "owner.stdout")
    require(summary["status"] == "closed_final_independent_audit"
            and summary["independent_audit_sha256"] == records.sha(work + "AUDIT.json")
            and summary["full_acceptance"] is False,
            "final audit owner output does not bind the independent result")
    for name, digest in scope["input_bindings"].items():
        require(records.sha(name) == digest, "accepted final audit input differs: " + name)
    readers = scope["reader_source_bindings"]
    require(isinstance(readers, dict) and readers
            and scope["independent_reader"]["path"] in readers
            and readers[scope["independent_reader"]["path"]]
            == scope["independent_reader"]["sha256"],
            "actual independent audit reader source is missing")
    for name, digest in readers.items():
        require(hashlib.sha256(source_bytes(checkout, name)).hexdigest() == digest,
                "executed independent audit reader source changed")
    require(result["schema"] == "caissa-final-independent-audit-v1"
            and result["status"] == "passed_final_independent_audit"
            and result["source_commit"] == expected_commit
            and result["engine_sha256"] == ENGINE and result["network_sha256"] == NETWORK
            and result["source_inventory_sha256"] == records.sha("SOURCE_INPUTS.json")
            and result["full_acceptance"] is False and result["release_authorized"] is False,
            "final audit scope/result is stale or promoted to project acceptance")
    require(set(result["areas"]) == AREAS and result["unresolved_findings"] == []
            and all(row["status"] == "passed" and row["scope_limits"]
                    and row["evidence_records"] for row in result["areas"].values()),
            "final audit area coverage or limitations incomplete")
    for row in result["areas"].values():
        for reference in row["evidence_records"]:
            require(records.sha(reference["path"]) == reference["sha256"],
                    "final audit review evidence changed")
    require(result["original_compiler_runtime_closure"] is False
            and result["absolute_rating_established"] is False,
            "audit report erased separate original compiler/runtime or rating gaps")
    audit = {"gate": "G16-audit", "source_commit": expected_commit,
             "engine_sha256": ENGINE, "network_sha256": NETWORK,
             "classification": "verified", "requirement_satisfied": True,
             "full_gate": True, "full_acceptance": False,
             "accepted_audit_sha256": ACCEPTED_AUDIT["result_sha256"],
             "original_compiler_runtime_closure": False}
    validate_projection_audit(audit, expected_commit)
    return audit
