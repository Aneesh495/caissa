"""Unexecuted G14 closed-join adapter, absent from the accepted full entry.

There is no accepted final G14 join yet. Its trust roots stay absent until an
admitted real join and independent review supply exact scope/result identities.
Bundle fields, a caller flag and historical sample receipts cannot install them.
"""

import hashlib

from verification.bundle import strict_json
from verification.final_evidence_bundle import ENGINE, NETWORK, boundary, owner, source_bytes
from verification.final_semantic_join import CHECKPOINT, MODEL, READERS
from verification.source import relative_path, require


DRIVER = "final-semantic-evidence-v1"
# Deliberately not an invented future scope path, digest or accepted result.
ACCEPTED_JOIN = None
BOUNDARY = "results/final-core-runtime-join-2026-10-28/BOUNDARY.json"


class SemanticRecords:
    def __init__(self, bundle, domain):
        require(ACCEPTED_JOIN is not None, "no admitted accepted final G14 join")
        descriptor = bundle.json(bundle.reference(domain["final_semantic_evidence"]))
        require(set(descriptor) == {"schema", "gate", "records"}
                and descriptor["schema"] == "caissa-final-semantic-records-v1"
                and descriptor["gate"] == "G14", "final G14 evidence descriptor differs")
        self.records = descriptor["records"]
        require(isinstance(self.records, dict) and 0 < len(self.records) <= 512,
                "final G14 raw inventory empty or excessive")
        for name, reference in self.records.items():
            relative_path(name)
            bundle.reference(reference)
        declared = {bundle.reference(x) for x in domain["artifacts"]}
        require(declared == {domain["final_semantic_evidence"]["path"],
                             *(x["path"] for x in self.records.values())},
                "final G14 raw inventory undeclared or excessive")
        self.bundle, self.cache, self.total = bundle, {}, 0
        work = ACCEPTED_JOIN["work"]
        require(work.endswith("/") and relative_path(work[:-1]), "invalid trusted G14 root")
        for name, digest in (("SCOPE.json", ACCEPTED_JOIN["scope_sha256"]),
                             ("SEMANTIC_JOIN.json", ACCEPTED_JOIN["result_sha256"])):
            require(self.sha(work + name) == digest, "accepted final G14 join changed")

    def raw(self, name):
        require(name in self.records, "required final G14 evidence missing: " + name)
        if name not in self.cache:
            raw = self.bundle.bytes(self.bundle.reference(self.records[name]), 16 * 1024**2)
            self.total += len(raw)
            require(self.total <= 40 * 1024**2, "final G14 metadata read ceiling exceeded")
            self.cache[name] = raw
        return self.cache[name]

    def sha(self, name):
        return hashlib.sha256(self.raw(name)).hexdigest()

    def doc(self, name):
        return strict_json(self.raw(name))


def verify_or_unverified(bundle, inputs, checkout, expected_commit):
    domain = inputs["domains"]["G14"]
    require(domain["source_commit"] == expected_commit and domain["driver"] == DRIVER
            and domain["engine_sha256"] == inputs["engine"]["sha256"] == ENGINE
            and domain["network_sha256"] == inputs["network"]["artifact"]["sha256"] == NETWORK,
            "final G14 driver or source differs")
    if ACCEPTED_JOIN is None:
        require(domain["artifacts"] == []
                and set(domain) == {"source_commit", "driver", "artifacts",
                                    "engine_sha256", "network_sha256"},
                "unaccepted G14 join artifacts cannot promote the gate")
        return {"gate": "G14", "source_commit": expected_commit,
                "engine_sha256": ENGINE, "network_sha256": NETWORK,
                "classification": "unverified", "requirement_satisfied": False,
                "reason": "final source join has no admitted accepted scope/result",
                "full_gate": False, "full_acceptance": False}

    records = SemanticRecords(bundle, domain)
    work = ACCEPTED_JOIN["work"]
    scope, result = records.doc(work + "SCOPE.json"), records.doc(work + "SEMANTIC_JOIN.json")
    closed = owner(records, work, ACCEPTED_JOIN["scope_sha256"])
    stdout = records.doc(work + "owner.stdout")
    require(closed["owned_group_absent_after_reap"] is True
            and stdout["status"] == result["status"]
            and stdout["controls"] == result["negative_controls"]
            and stdout["full_acceptance"] is False,
            "actual final G14 join owner/output differs")
    ledger = records.doc(work + "METADATA_USAGE.json")
    require(ledger["closed"] is True and ledger["failure"] is None
            and ledger["scope_sha256"] == ACCEPTED_JOIN["scope_sha256"]
            and ledger["native_starts"] == ledger["child_starts"] == 0,
            "final G14 join ledger is open, failed or differs")
    for name, digest in scope["input_bindings"].items():
        require(records.sha(name) == digest, "accepted G14 join input differs: " + name)
    require(result["status"] == "passed_final_G14_source_evidence_join"
            and result["engine_sha256"] == ENGINE and result["network_sha256"] == NETWORK
            and result["checkpoint_sha256"] == CHECKPOINT
            and result["original_model_campaign_sha256"] == MODEL
            and result["full_G14_current_source_join"] is True
            and result["full_G14_final_adapter_executed"] is False
            and result["full_acceptance"] is False,
            "accepted exact saved-image G14 source join incomplete")
    require((result["original_searches"], result["original_diagnostic_games"],
             result["original_selected_network_inferences"], result["original_draw_histories"],
             result["original_rehashed_semantic_rejections"], result["original_full_entry_cases"])
            == (4, 4, 4, 4, 16, 7)
            and result["strict_G11_and_G14_branch_AST_unchanged"] is True
            and result["closed_semantic_sample_or_control_reruns"] == 0,
            "accepted G14 coverage or historical preservation differs")
    deployment = records.doc(BOUNDARY)
    boundary(checkout, deployment)
    for name in [*READERS, "verification/full_bundle.py", "verification/final_semantic_join.py",
                 "tools/final_semantic_join.py", "verification/final_evidence_bundle.py",
                 "verification/final_core_bundle.py"]:
        require(hashlib.sha256(source_bytes(checkout, name)).hexdigest()
                == scope["input_bindings"][name], "final G14 source changed after accepted join")
    return {"gate": "G14", "source_commit": expected_commit,
            "engine_sha256": ENGINE, "network_sha256": NETWORK,
            "classification": "verified", "requirement_satisfied": True,
            "full_gate": True, "full_acceptance": False,
            "accepted_join_sha256": ACCEPTED_JOIN["result_sha256"],
            "native_starts": 0, "closed_semantic_sample_replays": 0,
            "original_compiler_runtime_closure": False}
