"""New G07 dispatch/provenance controls, without replaying earlier controls."""

import copy
import json
from pathlib import Path

from verification.bundle import Bundle
from verification.final_core_bundle import LINEAGE, integrate, verify
from verification.final_evidence_bundle import integrate as recovery_browser
from verification.source import require

ROOT = Path(__file__).resolve().parents[1]


def run_controls(fixture, inputs, manifest, put, ref, scope, quota):
    controls = []
    def adapter(current):
        with Bundle(fixture, 30) as bundle:
            bundle.verify_manifest()
            return verify(bundle, current, ROOT, scope["product_commit"], "G07")
    def reject(name, mutate):
        forged = copy.deepcopy(inputs)
        mutate(forged)
        try:
            adapter(forged)
        except (ValueError, KeyError) as error:
            controls.append({"case": name, "rejected": True, "reason": str(error)})
        else:
            raise ValueError("new lineage dispatch forgery accepted: " + name)
    reject("lineage_receipt_without_declared_evidence", lambda x: x["domains"]["G07"].update(artifacts=[]))
    reject("lineage_changed_saved_network", lambda x: x["domains"]["G07"].update(network_sha256="0" * 64))
    reject("lineage_stale_final_source", lambda x: x["domains"]["G07"].update(source_commit="0" * 40))
    reject("lineage_uses_performance_descriptor", lambda x: x["domains"]["G07"].update(final_evidence=x["domains"]["G13"]["final_evidence"]))
    def changed(name, missing=None, targets=None, mutate=None):
        index_name = inputs["domains"]["G07"]["final_evidence"]["path"]
        original_index = (fixture / index_name).read_bytes()
        index = json.loads(original_index)
        backups = {}
        if missing is not None:
            index["records"].pop(missing)
        for logical in targets or []:
            target = index["records"][logical]["path"]
            backups[target] = (fixture / target).read_bytes()
            value = json.loads(backups[target])
            mutate(value)
            put(target, value)
            index["records"][logical] = ref(target)
        put(index_name, index)
        forged = copy.deepcopy(inputs)
        forged["domains"]["G07"].update(final_evidence=ref(index_name), artifacts=[ref(index_name), *index["records"].values()])
        manifest()
        try:
            try:
                adapter(forged)
            except (ValueError, KeyError) as error:
                controls.append({"case": name, "rejected": True, "reason": str(error)})
            else:
                raise ValueError("rehashed lineage relationship accepted: " + name)
        finally:
            for target, original in backups.items():
                (fixture / target).write_bytes(original)
            (fixture / index_name).write_bytes(original_index)
            manifest()
    for label, name in [
        ("actual_learning_stage", "results/g07-full-audit-2026-10-26/execution/learning.json"),
        ("actual_original_data_reader", "results/g07-full-audit-2026-10-26/data/execution/independent.log"),
        ("historical_source_inventory", "results/g07-full-audit-2026-10-26/SOURCE_INPUTS.json"),
        ("original_training_branch_source", "work/final-data-learning-lineage-1-2026-10-29/original-train.py"),
        ("original_failed_model_receipt", "results/full-model-v3-2026-10-25/MODEL_CAMPAIGN.json"),
        ("closed_lineage_owner", LINEAGE + "CLOSED.json"),
        ("lineage_closed_metadata_ledger", LINEAGE + "METADATA_USAGE.json"),
    ]:
        changed("rehashed_missing_" + label, missing=name)
    changed("rehashed_failed_original_learning_stage", targets=["results/g07-full-audit-2026-10-26/execution/learning.json"], mutate=lambda x: x.update(exit=1))
    changed("rehashed_open_lineage_metadata_ledger", targets=[LINEAGE + "METADATA_USAGE.json"], mutate=lambda x: x.update(closed=False))
    changed("rehashed_claimed_full_raw_reproduction", targets=[LINEAGE + "AVAILABILITY.json", "results/final-data-learning-lineage-2026-10-29/AVAILABILITY.json"], mutate=lambda x: x.update(full_raw_reproduction_available=True))
    with Bundle(fixture, 30) as bundle:
        bundle.verify_manifest()
        review = {"full_acceptance": False, "pending_semantic_gates": {f"G{i:02d}": "pending" for i in range(1, 17) if i != 8}, "failed_semantic_gates": {"G08": {"status": "failed_original_neural_gain"}}}
        recovery_browser(bundle, inputs, ROOT, scope["product_commit"], review)
        integrate(bundle, inputs, ROOT, scope["product_commit"], review)
        require(set(review["verified_semantic_gates"]) == set(scope["expected_verified_gates"]) and set(review["pending_semantic_gates"]) == {"G10", "G14", "G15", "G16"} and review["failed_semantic_gates"]["G08"]["status"] == "failed_original_neural_gain" and review["full_acceptance"] is False, "lineage integration erased failed/incomplete/release gates")
        require(review["verified_semantic_gates"]["G07"]["full_historical_raw_reproduction"] is False and review["verified_semantic_gates"]["G07"]["new_training_or_selection"] is False, "lineage adapter manufactured raw reconstruction or selection")
        controls.append({"case": "eleven_domain_join_preserves_failed_incomplete_and_unavailable_decisions", "passed": True})
    return controls
