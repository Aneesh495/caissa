"""New Bundle dispatch cases for eight additional closed final domains."""

import copy
import json
from pathlib import Path

from verification.bundle import Bundle
from verification.final_core_bundle import DRIVERS, integrate, verify
from verification.final_evidence_bundle import integrate as integrate_recovery_browser
from verification.source import require

ROOT = Path(__file__).resolve().parents[1]


def run_controls(fixture, inputs, manifest, put, ref, scope, quota):
    controls = []

    def adapter(current, gate):
        with Bundle(fixture, 30) as bundle:
            bundle.verify_manifest()
            return verify(bundle, current, ROOT, scope["product_commit"], gate)

    def reject(name, gate, mutate):
        forged = copy.deepcopy(inputs)
        mutate(forged)
        try:
            adapter(forged, gate)
        except (ValueError, KeyError) as error:
            controls.append({"case": name, "rejected": True, "reason": str(error)})
        else:
            raise ValueError("new final-domain dispatch forgery accepted: " + name)

    reject("external_dispatch_changed_actor", "G09", lambda x: x["domains"]["G09"].__setitem__("engine_sha256", "0" * 64))
    reject("performance_dispatch_stale_source", "G13", lambda x: x["domains"]["G13"].__setitem__("source_commit", "0" * 40))
    reject("search_dispatched_as_performance", "G05", lambda x: x["domains"]["G05"].__setitem__("driver", DRIVERS["G13"]))
    reject("performance_given_core_descriptor", "G13", lambda x: x["domains"]["G13"].__setitem__("final_evidence", x["domains"]["G01"]["final_evidence"]))

    def changed(name, gate, missing=None, target_name=None, mutate=None):
        index_name = inputs["domains"][gate]["final_evidence"]["path"]
        original_index = (fixture / index_name).read_bytes()
        index = json.loads(original_index)
        original_target, target = None, None
        if missing is not None:
            index["records"].pop(missing)
        else:
            target = index["records"][target_name]["path"]
            original_target = (fixture / target).read_bytes()
            value = json.loads(original_target)
            mutate(value)
            put(target, value)
            index["records"][target_name] = ref(target)
        put(index_name, index)
        forged = copy.deepcopy(inputs)
        forged["domains"][gate]["final_evidence"] = ref(index_name)
        forged["domains"][gate]["artifacts"] = [ref(index_name), *index["records"].values()]
        manifest()
        try:
            try:
                adapter(forged, gate)
            except (ValueError, KeyError) as error:
                controls.append({"case": name, "rejected": True, "reason": str(error)})
            else:
                raise ValueError("rehashed final-domain relationship accepted: " + name)
        finally:
            if original_target is not None:
                (fixture / target).write_bytes(original_target)
            (fixture / index_name).write_bytes(original_index)
            manifest()

    missing = [
        ("G01", "rules_reader_missing", "runs/final-saved-actor-rules-2026-10-28/independent/RULES.json"),
        ("G02", "restoration_ledger_missing", "work/final-restoration-runtime-1-2026-10-28/WRITE_USAGE.json"),
        ("G03", "draw_owner_missing", "work/final-draw-runtime-1-2026-10-28/CLOSED.json"),
        ("G04", "protocol_stage_missing", "runs/final-saved-actor-protocol-2026-10-28/independent.json"),
        ("G05", "search_archived_reader_source_missing", "derived/G05_SOURCE_INPUTS.json"),
        ("G06", "numerical_reader_missing", "runs/final-saved-actor-numerical-2026-10-28/NUMERICAL_REPLAY.json"),
        ("G09", "external_real_independent_stage_missing", "runs/full-external-strength-v4/attempts/attempt-001/independent-external.json"),
        ("G13", "performance_actual_stage_missing", "results/performance-v4-2026-10-26/execution/independent.json"),
    ]
    for gate, name, path in missing:
        changed("rehashed_" + name, gate, missing=path)
    changed("rehashed_failed_restoration_owner", "G02", target_name="work/final-restoration-runtime-1-2026-10-28/CLOSED.json", mutate=lambda x: x.__setitem__("owner_exit", 1))
    changed("rehashed_incomplete_numerical_result", "G06", target_name="runs/final-saved-actor-numerical-2026-10-28/NUMERICAL_REPLAY.json", mutate=lambda x: x.__setitem__("probes", 99999))
    changed("rehashed_failed_original_external_stage", "G09", target_name="runs/full-external-strength-v4/attempts/attempt-001/independent-external.json", mutate=lambda x: x.__setitem__("exit", 1))

    # The new fixture routes immutable small input copies through data credits.
    # Test that route directly without changing a single retained input byte.
    require(quota.read()["data_used"] > 0, "immutable copied-data meter was not exercised")
    try:
        quota.classify(fixture / "lineage/engine")
    except ValueError:
        controls.append({"case": "copied_data_namespace_rejects_rewrite", "passed": True})
    else:
        raise ValueError("immutable copied-data writer accepted rewrite")

    with Bundle(fixture, 30) as bundle:
        bundle.verify_manifest()
        review = {"full_acceptance": False, "pending_semantic_gates": {f"G{i:02d}": "remaining" for i in range(1, 17) if i != 8}, "failed_semantic_gates": {"G08": {"status": "failed_original_neural_gain"}}}
        integrate_recovery_browser(bundle, inputs, ROOT, scope["product_commit"], review)
        integrate(bundle, inputs, ROOT, scope["product_commit"], review)
        require(set(review["verified_semantic_gates"]) == set(scope["expected_verified_gates"]) and set(review["pending_semantic_gates"]) == {"G07", "G10", "G14", "G15", "G16"} and review["failed_semantic_gates"]["G08"]["status"] == "failed_original_neural_gain" and review["full_acceptance"] is False, "additional accepted domains erased failed/unavailable gates")
        require(review["verified_semantic_gates"]["G13"]["full_G10_certified"] is False and "G10" not in review["verified_semantic_gates"], "performance component manufactured a full G10 pass")
        controls.append({"case": "ten_domain_projection_preserves_failure_and_incomplete_matrix", "passed": True})
    return controls
