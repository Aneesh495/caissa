"""Join the closed exact-image G14 sample to current independent sources."""

import ast
import hashlib
import json
import textwrap

ENGINE = "1ff25a97b2272f589aac40049f9c76e53228a3682f64489c72566dae449a9897"
NETWORK = "52d0306143392ad683c3ebb09fe013f34e1f9e2bc44d3aa153b32314207374b7"
CHECKPOINT = "c76d8e9ef0f2255531bc9085f5d0330a7a4152cf9b21a65ff8aee740ab8b2005"
MODEL = "92d62149d3a4de184ad93b9f5f04f77e38386992d04d02bd824b33cf3e5241bd"
ORIGINAL = "1deecce362cf12d9758e1af4bbebb5bbdda95fb1"
READERS = ["verification/semantic_audit.py", "verification/semantic_bundle.py", "verification/classical.py", "verification/network_bytes.py", "verification/draw_history.py", "verification/restoration_state.py", "verification/match_journals.py", "verification/verify.py", "verification/source.py", "verification/bundle.py", "verification/runtime_binding.py", "tools/semantic_witness.py", "tests/semantic_audit.py", "config/semantic-audit-v1.json"]
FAMILIES = ["illegal-pv", "swapped-result-colors", "mismatched-network-inference", "incorrect-draw-claim"]
REASONS = ["illegal semantic PV", "swapped result colors", "mismatched network inference", "incorrect draw claim"]


def require(value, reason):
    if not value:
        raise ValueError(reason)


def branch(raw, gate):
    source = raw.decode() if isinstance(raw, bytes) else raw
    start = source.index('        domain = inputs["domains"]["' + gate + '"]', source.index("def verify("))
    if gate == "G11":
        end = source.index('        domain = inputs["domains"]["G12"]', start)
        nodes = ast.parse(textwrap.dedent(source[start:end])).body
    else:
        end = source.index("        return review", start)
        nodes = ast.parse(textwrap.dedent(source[start:end])).body[:2]
        require(len(nodes) == 2 and isinstance(nodes[0], ast.Assign) and isinstance(nodes[1], ast.If), "historical G14 branch shape differs")
    return ast.dump(ast.Module(body=nodes, type_ignores=[]), include_attributes=False)


def validate(e):
    old, result, boundary = e["original"], e["archive"], e["boundary"]
    require(result["archive_bytes"] == 54893531 and result["archive_sha256"] == "45dd6642b18d9535e6e851c1d3f05231d6f950e4173013d33e7b56633c2fc0b3" and result["old_tests_or_controls_reexecuted"] == 0, "wrong original G14 archive or replay scope")
    require(e["owner"]["closed"] is True and type(e["owner"]["owner_exit"]) is int and e["owner"]["owner_exit"] == 0 and e["owner"]["stderr_bytes"] == 0 and e["owner"]["scope_sha256"] == e["archive_scope_sha256"], "actual G14 archive owner failed or changed")
    require(e["transport"]["exit"] == 0 and e["transport"]["stderr_bytes"] == 0 and e["transport"]["owned_group_absent_after_reap"] is True and e["ledger"]["closed"] is True and e["ledger"]["failure"] is None and e["ledger"]["scope_sha256"] == e["archive_scope_sha256"], "G14 transport or closed ledger differs")
    require(old["status"] == "passed" and old["gate"] == "G14" and old["full_gate"] is True and old["full_acceptance"] is False and old["source_commit"] == ORIGINAL and old["engine_sha256"] == ENGINE and old["network_sha256"] == NETWORK, "original exact saved-image G14 acceptance differs")
    positive = old["positive_witnesses"]
    require(positive["witness_pass"] is True and positive["status"] == "passed" and positive["searches"] == positive["game_journals"] == positive["selected_network_inferences"] == positive["draw_histories"] == 4 and positive["full_gate"] is False and positive["full_acceptance"] is False, "original complete four-family witness inventory differs")
    expected = [(f, n) for f in FAMILIES for n in range(4)]
    require([(r["family"], r["variant"]) for r in old["rehashed_semantic_rejections"]] == expected and [(r["family"], r["variant"]) for r in e["rejection_manifests"]] == expected, "original 16-case mutation schedule incomplete")
    for row, raw in zip(old["rehashed_semantic_rejections"], e["rejection_manifests"], strict=True):
        require(row["rehashed_manifest_sha256"] == raw["manifest_sha256"] and row["rejection"] == raw["recorded_rejection"] and REASONS[FAMILIES.index(row["family"])] in row["rejection"] and raw["files"] == 23, "recorded semantic rejection/raw manifest relationship differs")
    config, manifest = e["config"], e["raw_manifest"]
    require(config["source_commit"] == ORIGINAL and config["engine_sha256"] == ENGINE and config["network_sha256"] == NETWORK and config["profile_sha256"] == e["raw_pins"]["PROFILE.json"] and e["raw_manifest_sha256"] == old["original_manifest_sha256"], "original G14 frozen raw/source/profile differs")
    require(e["raw_pins"] == result["raw_positive_sha256"] and manifest["files"] == {n: h for n, h in e["raw_pins"].items() if n != "MANIFEST.json"} and e["raw_pins"]["engine"] == ENGINE and e["raw_pins"]["network.cai"] == NETWORK, "original positive raw inventory differs")
    cases = e["cases"]
    require(set(cases) == {"positive-full-entry", "missing-replay-output", *FAMILIES, "undeclared-raw-artifact"}, "actual original full-entry case inventory incomplete")
    for name, row in cases.items():
        expected_exit = 2 if name in {"positive-full-entry", "missing-replay-output"} else 1
        require(type(row["exit"]) is int and row["exit"] == expected_exit and row["stderr"] == "" and row["stdout"]["full_acceptance"] is False and row["ordinary_manifest_and_external_pin_recomputed"] is True, "actual original full-entry exit or failed decision differs")
    require(cases["positive-full-entry"]["stdout"]["verified_semantic_gates"]["G14"] == old and len(cases["positive-full-entry"]["stdout"]["pending_semantic_gates"]) == 15 and len(cases["missing-replay-output"]["stdout"]["pending_semantic_gates"]) == 16, "original full-entry independent decision differs")
    native = old["saved_native_source_binding"]
    require(native["engine_sha256"] == boundary["engine_sha256"] == ENGINE and native["network_sha256"] == boundary["network_sha256"] == NETWORK and native["checkpoint_sha256"] == boundary["checkpoint_sha256"] == CHECKPOINT and native["original_model_campaign_sha256"] == MODEL and native["compiled_source_commit"] == boundary["compiled_source_commit"], "original G14 final native/model/checkpoint relationship differs")
    require(native["native_source_sha256"] == boundary["native_source_sha256"] == e["current_native_sha256"] and native["native_source_modes"] == boundary["native_source_modes"] == e["current_native_modes"] and native["matched_native_files"] == 69, "original/current final 69-file source or mode differs")
    source = e["original_source_inventory"]
    require(source["commit"] == ORIGINAL and e["reader_source_sha256"] == {n: source["files"][n] for n in READERS}, "executed G14 independent reader/producer footprint changed")
    require(e["G14_legacy_branch_AST_equal"] is True and e["G11_strict_branch_AST_equal"] is True and e["current_original_reader_hash"] == source["files"]["verification/semantic_audit.py"], "strict historical branch or independent semantic reader changed")
    current = e["accepted_eleven_domain_report"]
    require(current["status"] == "incomplete" and current["full_acceptance"] is False and set(current["verified_semantic_gates"]) == {f"G{i:02d}" for i in range(1, 8)} | {"G09", "G11", "G12", "G13"} and set(current["pending_semantic_gates"]) == {"G08", "G10", "G14", "G15", "G16"}, "earlier accepted domains or unresolved gates changed")
    require(e["eleven_domain_stage"]["exit"] == 2 and e["eleven_domain_stage"]["cleanup_warnings"] == [] and e["eleven_domain_stage"]["log_sha256"] == e["eleven_domain_log_sha256"] and e["prior_final_adapter_sources_match"] is True, "actual earlier eleven-domain process or final adapter sources differ")
    return {"status": "passed_final_G14_source_evidence_join", "engine_sha256": ENGINE, "network_sha256": NETWORK, "checkpoint_sha256": CHECKPOINT, "original_model_campaign_sha256": MODEL, "matched_native_files": 69, "original_searches": 4, "original_diagnostic_games": 4, "original_selected_network_inferences": 4, "original_draw_histories": 4, "original_rehashed_semantic_rejections": 16, "original_full_entry_cases": 7, "unchanged_semantic_source_footprint": len(READERS), "strict_G11_and_G14_branch_AST_unchanged": True, "accepted_other_domains": 11, "closed_semantic_sample_or_control_reruns": 0, "native_starts": 0, "full_G14_current_source_join": True, "full_G14_final_adapter_executed": False, "original_compiler_runtime_closure": False, "full_R12_complete": False, "full_acceptance": False}
