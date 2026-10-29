"""Check retained data/learning lineage without replaying or selecting a model."""

import ast
import hashlib
import json

DATA = "f09cdec986858c5b1aa80b3c97aaa4d825be892fc94e16ac5d835bc3d709f0ce"
CHECKPOINT = "c76d8e9ef0f2255531bc9085f5d0330a7a4152cf9b21a65ff8aee740ab8b2005"
MODEL = "92d62149d3a4de184ad93b9f5f04f77e38386992d04d02bd824b33cf3e5241bd"
NETWORK = "52d0306143392ad683c3ebb09fe013f34e1f9e2bc44d3aa153b32314207374b7"
OLD_NETWORK = "c251670ec53ba38a680c16cc6199be48f89cc829dd5483197e6d4b39ac6debf6"
ENGINE = "1ff25a97b2272f589aac40049f9c76e53228a3682f64489c72566dae449a9897"
G07 = "results/g07-full-audit-2026-10-26/"
LEARNING = "results/full-model-v3-2026-10-25/"
BOUNDARY = "results/final-core-runtime-join-2026-10-28/BOUNDARY.json"
SPLITS = {"train": 10578434, "validation": 1336496, "test": 1301363}
READERS = ["tools/full_learning.py", "tools/finalize_corpus.py", "verification/g07_audit.py", "verification/data_catalog.py", "verification/learning.py", "verification/learning_bundle.py"]
TRAINING = ["training/" + name + ".py" for name in ["__init__", "baselines", "corpus", "data_profile", "export", "features", "model", "prepare", "select", "train"]]


def require(value, reason):
    if not value:
        raise ValueError(reason)


def equal(a, b):
    return type(a) is type(b) and (a.keys() == b.keys() and all(equal(a[k], b[k]) for k in a) if isinstance(a, dict) else len(a) == len(b) and all(equal(x, y) for x, y in zip(a, b)) if isinstance(a, list) else a == b)


def ordinary_ast(raw, name):
    """Remove only the reviewed optional recovery branches from current source.

    The historical training commands did not enable resume or recovery barriers.
    The branches themselves remain covered by separate recovery evidence.
    """
    tree = ast.parse(raw)
    removed = []

    class Ordinary(ast.NodeTransformer):
        def visit_Import(self, node):
            if name == "training/prepare.py" and [n.name for n in node.names] == ["argparse", "hashlib", "json", "math", "sqlite3", "time", "fcntl", "os"]:
                node.names.pop()
                removed.append("prepare optional barrier os import")
            return node

        def visit_Expr(self, node):
            if ast.unparse(node) == "ap.add_argument('--recovery-barrier', type=Path)":
                removed.append("optional barrier argument with implicit None default")
                return None
            return self.generic_visit(node)

        def visit_If(self, node):
            test = ast.unparse(node.test)
            barriers = {"a.recovery_barrier is not None"} if name == "training/prepare.py" else set()
            if name == "training/prepare.py":
                barriers |= {"a.recovery_barrier is not None and session_pairs == 32", "a.recovery_barrier is not None and session_pairs == 52"}
            else:
                barriers.add("a.recovery_barrier is not None and step + 1 == 40")
            train_guard = name == "training/train.py" and isinstance(node.test, ast.BoolOp) and isinstance(node.test.op, ast.And) and ast.unparse(node.test.values[0]) == "a.recovery_barrier is not None" and isinstance(node.test.values[1], ast.BoolOp)
            if test in barriers or train_guard:
                require(not node.orelse, "optional recovery branch gained an else")
                removed.append("barrier branch: " + test)
                return None
            if name == "training/train.py" and ast.unparse(node) == "if a.resume:\n    from training.journal import recover\n    recover(a.output, first_step, a.checkpoint_every)":
                removed.append("resume-only journal repair")
                return None
            return self.generic_visit(node)

        def visit_List(self, node):
            if name == "training/train.py" and [x.value for x in node.elts if isinstance(x, ast.Constant)] == ["resume", "output", "dataset", "network_version", "baseline_directory", "recovery_barrier"]:
                node.elts.pop()
                removed.append("exclude optional argument from original config")
            return self.generic_visit(node)

    transformed = Ordinary().visit(tree)
    require(len(removed) == 5, "optional recovery source inventory differs")
    return ast.dump(transformed, include_attributes=False), removed


def validate(e):
    d, h, available = e["documents"], e["identities"], e["availability"]
    old, plan = d[G07 + "G07.json"], d[G07 + "PLAN.json"]
    data, learned = d[G07 + "data/DATA.json"], d[G07 + "learning/LEARNING.json"]
    model, selection, dataset = d[LEARNING + "MODEL_CAMPAIGN.json"], d[LEARNING + "SELECTION.json"], d["results/full-data-2026-10-25/DATASET.json"]
    boundary = d[BOUNDARY]
    require(old["status"] == "passed" and old["full_gate"] is True and old["full_acceptance"] is False and old["scope_closed"] is True, "historical G07 was not a completed independent gate")
    require(old["plan_sha256"] == h[G07 + "PLAN.json"] and old["source_commit"] == plan["source_commit"] == d[G07 + "SOURCE_INPUTS.json"]["commit"], "original G07 plan/source join differs")
    for component, actual in [("data", data), ("learning", learned)]:
        path = G07 + old["components"][component]["path"]
        require(old["components"][component]["sha256"] == h[path] and equal(actual, d[G07 + "execution/" + component + ".log"]), "actual original component output differs")
        require(actual["status"] == "passed" and actual["component_pass"] is True and actual["full_gate"] is False and actual["full_acceptance"] is False and actual["dataset_sha256"] == DATA, "historical component failed or was promoted")
    for base, label in [(G07 + "execution/", "data"), (G07 + "execution/", "learning"), (G07 + "data/execution/", "independent")]:
        stage = d[base + label + ".json"]
        require(type(stage["exit"]) is int and stage["exit"] == 0 and stage["reason"] == "completed" and stage["cleanup_warnings"] == [] and stage["discarded_output_bytes"] == 0 and stage["log_sha256"] == h[base + label + ".log"], "actual original G07 stage failed or log/cleanup differs")
    for name in ["ACTIVE_USAGE.json", "data/ACTIVE_USAGE.json"]:
        require(d[G07 + name]["closed"] is True, "historical G07 active ledger remains open")
    raw_data = d[G07 + "data/execution/independent.log"]
    require(all(equal(v, data[k]) for k, v in raw_data.items()), "original full data independent output differs")
    require(data["source_pairs"] == 114791 and data["completed_games"] == 229582 and data["raw_samples"] == 16522987 and data["independently_rebuilt_splits"] == dataset["splits"] == SPLITS and data["original_acquisition_status"] == "failed-preserved", "original complete data schedule or failure changed")
    require(learned["seeds"] == [17, 41, 73] and type(learned["all_checkpoints_independently_evaluated"]) is int and learned["all_checkpoints_independently_evaluated"] == 240 and learned["validation_positions_per_checkpoint"] == 8192 and learned["test_arrays_opened"] is False, "original complete learning schedule differs")
    lineage = learned["original_lineage"]
    require(h[LEARNING + "MODEL_CAMPAIGN.json"] == MODEL == lineage["original_model_campaign_sha256"] and lineage["checkpoint_sha256"] == CHECKPOINT and lineage["original_network_sha256"] == OLD_NETWORK and lineage["deployed_network_sha256"] == NETWORK and lineage["new_learning_receipt_created"] is False, "original float/export lineage changed")
    require(model["failed_domains"] == ["G06 producer numerical endpoint", "G06 independent numerical endpoint"] and lineage["original_failed_domains"] == model["failed_domains"], "old numerical failures were erased")
    require(h[LEARNING + "SELECTION.json"] == lineage["original_selection_sha256"] and selection["test_accessed"] is False and selection["dataset_sha256"] == DATA and learned["selected_seed"] == selection["selected"]["seed"] == 73 and learned["selected_step"] == selection["selected"]["step"] == 2750 and selection["selected"]["checkpoint_sha256"] == CHECKPOINT, "original frozen selection differs")
    observed = learned["independent_seed_observations"]
    require([r["seed"] for r in observed] == [17, 41, 73] and all([x["step"] for x in r["independent_checkpoint_validation"]] == list(range(250, 20001, 250)) for r in observed), "historical learning checkpoint inventory incomplete")
    require(h["results/full-data-2026-10-25/DATASET.json"] == DATA and dataset["corpus_config"]["engine_sha256"] == e["teacher_sha256"] and e["teacher_sha256"] != ENGINE, "historical teacher was replaced by final deployment")
    require(boundary["engine_sha256"] == ENGINE and boundary["network_sha256"] == NETWORK and boundary["checkpoint_sha256"] == CHECKPOINT and e["retained_engine_sha256"] == ENGINE and e["retained_network_sha256"] == NETWORK and e["retained_checkpoint_sha256"] == CHECKPOINT, "retained deployment bytes differ")
    require(e["network_header_checkpoint"] == CHECKPOINT and e["network_header_version"] == 4, "retained inference network embeds a different float checkpoint")
    require(e["native_hashes"] == boundary["native_source_sha256"] and e["native_modes"] == boundary["native_source_modes"] and len(e["native_hashes"]) == 69, "final native source or mode differs")
    original_sources = d[G07 + "SOURCE_INPUTS.json"]["files"]
    for name in READERS + TRAINING:
        if name not in ("training/train.py", "training/prepare.py"):
            require(e["current_source_sha256"][name] == original_sources[name], "original independent learning/data source changed: " + name)
    require(e["ordinary_source_AST_equal"] == {"training/train.py": True, "training/prepare.py": True} and e["historical_training_used_resume"] is False, "current ordinary training/preparation path differs or was resumed")
    require(set(available["original_checkpoint_paths"]) == {f"runs/searched-full-model-v3/seed{seed}/checkpoints/step-{step:08d}.pt" for seed in (17, 41, 73) for step in range(250, 20001, 250)} and not any(available["original_checkpoint_paths"].values()), "retired original checkpoint availability differs")
    require(available["selected_alternate"]["path"] == "results/precision-v4-inputs/selected.pt" and available["selected_alternate"]["sha256"] == CHECKPOINT and available["selected_alternate"]["bytes"] == 9518976, "retained alternate selected checkpoint missing")
    catalogs = {plan["data"]["catalog"], plan["learning"]["root"] + "/MANIFEST.json", plan["learning"]["root"] + "/INPUTS.json"}
    require(set(available["original_array_paths"]) == {"data/searched-full-v3-prepared/" + n for n in dataset["files"]} and not any(available["original_array_paths"].values()) and set(available["original_audit_catalog_paths"]) == catalogs and not any(available["original_audit_catalog_paths"].values()), "retired full arrays/catalog availability differs")
    sliced = d["results/precision-v4-inputs/validation/SLICE.json"]
    require(sliced["rows"] == 8192 and sliced["dataset_sha256"] == DATA and sliced["parent_feature_sha256"] == dataset["files"]["validation-features.npy"] and sliced["parent_target_sha256"] == dataset["files"]["validation-targets.npy"] and sliced["test_arrays_opened"] is False, "retained validation slice provenance differs")
    require(available["retained_validation_slice_sha256"] == sliced["files"] and available["full_raw_reproduction_available"] is False and e["new_training"] is False and e["new_selection"] is False and e["full_acceptance"] is False, "slice or lineage was promoted to reproduction/training/release")
    return {"status": "passed_final_data_learning_lineage", "historical_G07_pass_bound": True, "dataset_sha256": DATA, "original_teacher_sha256": e["teacher_sha256"], "engine_sha256": ENGINE, "network_sha256": NETWORK, "checkpoint_sha256": CHECKPOINT, "original_model_campaign_sha256": MODEL, "original_selected_seed": 73, "original_selected_step": 2750, "original_checkpoints_audited": 240, "retained_selected_checkpoint_bytes": 9518976, "original_checkpoint_paths_available": 0, "original_full_arrays_available": 0, "retained_validation_rows": 8192, "original_numerical_failures_preserved": model["failed_domains"], "matched_native_files": 69, "unchanged_independent_and_training_sources": 14, "ordinary_training_preparation_AST_matches": True, "optional_recovery_branches_remain_separate": True, "new_training": False, "new_selection": False, "full_raw_reproduction_available": False, "full_G07_coordinator_integrated": False, "original_compiler_runtime_closure": False, "full_acceptance": False}
