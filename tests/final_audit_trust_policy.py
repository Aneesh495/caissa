"""Unexecuted synthetic external-root policy cases, with no files or owners.

The fixture is not an accepted audit receipt. No root file is written, and no
scope is registered. A future admitted owner must execute these new cases once.
"""

from dataclasses import FrozenInstanceError
import hashlib
import json

from verification.final_audit_trust import decode_external_trust
from verification.source import require


SOURCE, INVENTORY = "1" * 40, "5" * 64


def fixture():
    return {"schema": "caissa-final-audit-external-trust-v1",
            "scope_path": "work/synthetic-audit-policy/SCOPE.json",
            "scope_sha256": "2" * 64, "result_sha256": "3" * 64,
            "owner_closed_sha256": "4" * 64,
            "source_commit": SOURCE, "source_inventory_sha256": INVENTORY}


def encode(doc):
    return json.dumps(doc, sort_keys=True, separators=(",", ":")).encode()


def run_controls():
    cases = []
    original = encode(fixture())
    original_sha = hashlib.sha256(original).hexdigest()

    def reject(name, raw, expected_sha):
        try:
            decode_external_trust(raw, expected_sha, SOURCE, INVENTORY)
        except (ValueError, KeyError, TypeError) as error:
            cases.append({"case": name, "rejected": True, "reason": str(error)})
        else:
            raise ValueError("new external audit root forgery accepted: " + name)

    changed = fixture()
    changed["result_sha256"] = "6" * 64
    reject("changed_receipt_cannot_follow_bundle_rehash", encode(changed), original_sha)
    for name, change in [
        ("stale_audited_commit", {"source_commit": "7" * 40}),
        ("stale_audited_inventory", {"source_inventory_sha256": "7" * 64}),
        ("caller_audit_pass_flag", {"full_acceptance": True}),
        ("malformed_result_identity", {"result_sha256": True}),
        ("escaped_scope_path", {"scope_path": "work/../elsewhere/SCOPE.json"}),
        ("non_work_scope_root", {"scope_path": ".agent-local/synthetic/SCOPE.json"}),
    ]:
        doc = fixture()
        doc.update(change)
        raw = encode(doc)
        reject(name, raw, hashlib.sha256(raw).hexdigest())
    duplicate = original[:-1] + b',"source_commit":"' + SOURCE.encode() + b'"}'
    reject("duplicate_receipt_key", duplicate, hashlib.sha256(duplicate).hexdigest())
    trust = decode_external_trust(original, original_sha, SOURCE, INVENTORY)
    require(trust.source_commit == SOURCE and trust.source_inventory_sha256 == INVENTORY
            and trust.result_sha256 == fixture()["result_sha256"]
            and trust.owner_closed_sha256 == fixture()["owner_closed_sha256"]
            and trust.receipt_sha256 == original_sha,
            "external receipt decoding changed a synthetic pinned identity")
    try:
        trust.result_sha256 = "0" * 64
    except FrozenInstanceError:
        pass
    else:
        raise ValueError("admitted audit trust object is mutable")
    cases.append({"case": "exact_external_identity_preserved_and_immutable",
                  "synthetic_policy_check": True, "real_audit_accepted": False})
    return {"status": "passed_new_synthetic_external_audit_trust_policy_controls",
            "controls": len(cases), "cases": cases, "files_written": 0,
            "real_audit_roots_loaded": 0, "full_acceptance": False}
