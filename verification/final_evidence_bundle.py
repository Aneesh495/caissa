"""Integrate closed final evidence without restarting accepted domain samples.

The two fixed scopes and accepted independent outputs are trust anchors. Bundle
integrity alone is insufficient: actual exits, raw inventories, current source
and saved actors must also agree. Historical adapters keep their own contracts.
"""

import ast
import hashlib
from pathlib import Path
import textwrap

from verification.bundle import strict_json
from verification.source import relative_path, require


ENGINE = "1ff25a97b2272f589aac40049f9c76e53228a3682f64489c72566dae449a9897"
NETWORK = "52d0306143392ad683c3ebb09fe013f34e1f9e2bc44d3aa153b32314207374b7"
G11_RUN = "runs/final-current-recovery-2026-10-29/"
G11_WORK = "work/final-recovery-runtime-1-2026-10-29/"
G11_JOIN = "work/final-recovery-join-1-2026-10-29/"
G12_RUN = "runs/final-served-browser-2-2026-10-29/"
G12_WORK = "work/final-browser-runtime-3-2026-10-29/"
ANCHORS = {
    "G11": {
        G11_WORK + "SCOPE.json": "6276bb6d1aa9213a6f94ab3f846c32ef57df14fab57adc244df4cc4213ff87d6",
        G11_JOIN + "SCOPE.json": "6f2fd20297e5e0b3e73343254457ad04c110cfd8b66d14c384c9613f414d4b83",
        G11_JOIN + "RECOVERY_JOIN.json": "ee1ce99a015618b4ba5a416bdf71d325d8145522ed77e097b9938b8697a3fec1",
    },
    "G12": {
        G12_WORK + "SCOPE.json": "3ce0fb5c474e2ab5c303fd778be38fe5273c4107dc0bd0c877da4bdada5cdc19",
        "results/final-served-browser-2026-10-29/FINAL_BROWSER.json": "5b5409e9d73139a6e1e16b6f0bb8acd1f69fc72dbb9d52facfdd499388fd2e0f",
        "results/final-served-browser-2026-10-29/PRIVATE_EVIDENCE_INDEX.json": "d673a4c7869f5df14901630fa7c309c3eb8c163361e6656eb44633cb7b245e06",
    },
}
DRIVERS = {"G11": "final-recovery-evidence-v1", "G12": "final-served-browser-evidence-v1"}


class Records:
    def __init__(self, bundle, domain, gate):
        descriptor = bundle.json(bundle.reference(domain["final_evidence"]))
        require(
            set(descriptor) == {"schema", "gate", "records"}
            and descriptor["schema"] == "caissa-closed-final-domain-v1"
            and descriptor["gate"] == gate,
            "final evidence descriptor or gate differs",
        )
        records = descriptor["records"]
        require(isinstance(records, dict) and 0 < len(records) <= 512, "final raw inventory empty or excessive")
        for name, reference in records.items():
            relative_path(name)
            bundle.reference(reference)
        declared = {bundle.reference(x) for x in domain["artifacts"]}
        require(
            {domain["final_evidence"]["path"], *(x["path"] for x in records.values())} == declared,
            "final raw inventory is undeclared, missing or excessive",
        )
        self.bundle, self.records, self.total, self.cache = bundle, records, 0, {}
        for name, digest in ANCHORS[gate].items():
            require(self.sha(name) == digest, "accepted final scope or independent output changed")

    def raw(self, name):
        require(name in self.records, "required final raw artifact missing: " + name)
        if name not in self.cache:
            raw = self.bundle.bytes(self.bundle.reference(self.records[name]), 16 * 1024**2)
            self.total += len(raw)
            require(self.total <= 40 * 1024**2, "final domain read ceiling exceeded")
            self.cache[name] = raw
        return self.cache[name]

    def sha(self, name):
        return hashlib.sha256(self.raw(name)).hexdigest()

    def doc(self, name):
        return strict_json(self.raw(name))


def source_bytes(checkout, name):
    path = Path(checkout).resolve() / relative_path(name)
    require(path.resolve() == path and path.is_file() and path.stat().st_size <= 4 * 1024**2, "final source is missing, linked or excessive")
    return path.read_bytes()


def current_sources(checkout, scope, names):
    bindings = scope["source_bindings"]
    for name in names:
        expected = bindings.get(name, bindings.get(str(Path(scope["root"]) / name)))
        require(expected is not None and hashlib.sha256(source_bytes(checkout, name)).hexdigest() == expected, "final executed source differs: " + name)


def boundary(checkout, expected):
    require(expected["engine_sha256"] == ENGINE and expected["network_sha256"] == NETWORK, "final saved actor boundary differs")
    require(len(expected["native_source_sha256"]) == len(expected["native_source_modes"]) == 69, "final native source inventory incomplete")
    for name, digest in expected["native_source_sha256"].items():
        require(hashlib.sha256(source_bytes(checkout, name)).hexdigest() == digest, "final native source bytes differ")
        mode = "100755" if (Path(checkout) / name).stat().st_mode & 0o111 else "100644"
        require(mode == expected["native_source_modes"][name], "final native source mode differs")


def stage(records, prefix, label, code=0):
    receipt = records.doc(prefix + label + ".json")
    require(
        type(receipt["exit"]) is int and receipt["exit"] == code
        and receipt["cleanup_warnings"] == [] and receipt["discarded_output_bytes"] == 0
        and records.sha(prefix + label + ".log") == receipt["log_sha256"],
        "actual final independent/producer stage failed or differs",
    )
    return receipt


def owner(records, work, scope_hash):
    receipt = records.doc(work + "CLOSED.json")
    require(
        receipt["closed"] is True and type(receipt["owner_exit"]) is int
        and receipt["owner_exit"] == 0 and receipt["scope_sha256"] == scope_hash
        and receipt["stderr_bytes"] == 0,
        "final owner did not close cleanly",
    )
    for channel in ["stdout", "stderr"]:
        require(records.sha(work + "owner." + channel) == receipt[channel + "_sha256"], "actual final owner log differs")
    return receipt


def runtime_closed(records, run, work, scope, expected_groups):
    owner(records, work, records.sha(work + "SCOPE.json"))
    active, writes, groups = (records.doc(run + "ACTIVE_USAGE.json"), records.doc(work + "WRITE_USAGE.json"), records.doc(run + "GROUPS.json"))
    require(active["closed"] is True and 0 < active["active_seconds"] <= scope["maximum_active_seconds"], "final active ledger open or exhausted")
    require(writes["closed"] is True and writes.get("failure") is None and writes["scope_sha256"] == records.sha(work + "SCOPE.json"), "final write ledger open or failed")
    require([x["stage"] for x in groups] == expected_groups and all(x["group_absent_after_reap"] is True for x in groups), "final owned process groups survived or differ")


def g11(records, checkout):
    scope, joined = records.doc(G11_WORK + "SCOPE.json"), records.doc(G11_JOIN + "SCOPE.json")
    result = records.doc(G11_JOIN + "RECOVERY_JOIN.json")
    require(result["full_R09_complete"] is True and result["status"] == "passed_final_recovery_evidence_join" and result["full_acceptance"] is False, "final independent recovery result is incomplete")
    require((result["engine_sha256"], result["network_sha256"]) == (ENGINE, NETWORK), "final recovery actor differs")
    owner(records, G11_JOIN, records.sha(G11_JOIN + "SCOPE.json"))
    require(strict_json(records.raw(G11_JOIN + "owner.stdout")) == result, "actual recovery join output differs")
    require(set(joined["raw_runtime_inventory"]) <= set(records.records), "final recovery raw inventory incomplete")
    for name in joined["raw_runtime_inventory"]:
        require(records.sha(name) == joined["source_bindings"][name], "final recovery raw bytes differ from accepted join")
    for name in ["results/final-recovery-evidence-2026-10-29/ORIGINAL_G11.json", "results/final-recovery-evidence-2026-10-29/ORIGINAL_FULL_ENTRY.json", "work/final-recovery-archive-1-2026-10-29/RESULT.json"]:
        require(records.sha(name) == joined["source_bindings"][name], "original recovery relationship differs")
    original = records.doc("results/final-recovery-evidence-2026-10-29/ORIGINAL_G11.json")
    require(original["full_G11_saved_image_sample"] is True and original["full_gate"] is True and original["full_acceptance"] is False, "original full recovery evidence absent")
    b = records.doc("results/final-core-runtime-join-2026-10-28/BOUNDARY.json")
    require(records.sha("results/final-core-runtime-join-2026-10-28/BOUNDARY.json") == joined["source_bindings"]["results/final-core-runtime-join-2026-10-28/BOUNDARY.json"], "final recovery boundary differs from accepted join")
    boundary(checkout, b)
    current_sources(checkout, scope, ["arena/run.py", "verification/final_recovery.py", "tools/final_recovery_runtime.py"])
    current_sources(checkout, joined, ["verification/final_recovery_join.py"])
    for name in ["verification/recovery_join.py", "verification/recovery_join_bundle.py", "verification/recovery_bundle.py", "tools/train.py", "tools/prepare_data.py"]:
        if name in joined["source_bindings"]:
            current_sources(checkout, joined, [name])
    runtime_closed(records, G11_RUN, G11_WORK, scope, ["interrupted", "resumed", "independent"])
    for label, code in [("interrupted", -9), ("resumed", 0), ("independent", 0)]:
        stage(records, G11_RUN, label, code)
    runtime = records.doc(G11_RUN + "CURRENT_RECOVERY.json")
    require(runtime == records.doc(G11_RUN + "independent/FINAL_RECOVERY.json") and runtime["scope_sha256"] == records.sha(G11_WORK + "SCOPE.json") and runtime["normal_native_exits"] == runtime["applied_model_acknowledgements"] == 12, "actual final recovery reader or model/native closure differs")
    old = records.raw(G11_JOIN + "ORIGINAL_FULL_BUNDLE.py").decode()
    def branch(text):
        first = text.index('        domain = inputs["domains"]["G11"]')
        last = text.index('        domain = inputs["domains"]["G12"]', first)
        return ast.dump(ast.parse(textwrap.dedent(text[first:last])), include_attributes=False)
    require(branch(source_bytes(checkout, "verification/full_bundle.py").decode()) == branch(old), "strict historical recovery coordinator branch changed")
    return {"accepted_independent_result": records.sha(G11_JOIN + "RECOVERY_JOIN.json"), "raw_files_bound_to_original_join": len(joined["raw_runtime_inventory"]), "historical_samples_reexecuted": False}


def g12(records, checkout):
    scope = records.doc(G12_WORK + "SCOPE.json")
    result = records.doc("results/final-served-browser-2026-10-29/FINAL_BROWSER.json")
    require(result == records.doc(G12_RUN + "independent/FINAL_BROWSER.json") == records.doc(G12_RUN + "FINAL_BROWSER.json"), "published final browser result differs from actual independent artifact")
    require(result["full_R10_complete"] is True and result["full_acceptance"] is False and result["status"] == "passed_final_served_browser_domain", "final browser independent result incomplete")
    index = records.doc("results/final-served-browser-2026-10-29/PRIVATE_EVIDENCE_INDEX.json")
    for name, entry in index["files"].items():
        raw = records.raw(G12_RUN + name)
        require(len(raw) == entry["bytes"] and hashlib.sha256(raw).hexdigest() == entry["sha256"], "accepted browser raw evidence changed")
    runtime_closed(records, G12_RUN, G12_WORK, scope, ["capture", "independent"])
    for label in ["compiler-stage", "capture", "independent"]:
        stage(records, G12_RUN, label)
    require(strict_json(records.raw(G12_RUN + "independent.log")) == result, "actual final browser reader output differs")
    require(result["scope_sha256"] == records.sha(G12_WORK + "SCOPE.json") and result["engine_sha256"] == scope["engine_sha256"] == ENGINE and result["network_sha256"] == scope["network_sha256"] == NETWORK, "final browser scope or native actor differs")
    boundary(checkout, {"engine_sha256": scope["engine_sha256"], "network_sha256": scope["network_sha256"], "native_source_sha256": scope["native_source_hashes"], "native_source_modes": scope["native_source_modes"]})
    names = ["web/app.ts", "web/index.html", "web/style.css", "analysis-service/native.ts", "analysis-service/server.ts", "analysis-service/telemetry.ts", "tsconfig.json", "package.json", "package-lock.json", "config/final-browser-runtime-v1.json", "verification/final_browser.py", "verification/browser.py", "tools/final_browser_runtime.py", "tools/final_browser_build.mjs", "tools/final_browser_capture.mjs", "tools/final_browser_process.cjs"]
    current_sources(checkout, scope, names)
    hook = "tools/final_browser_process.cjs"
    require((Path(checkout) / hook).stat().st_mode & 0o111 == 0, "explicit final process helper source mode changed")
    build = records.doc(G12_RUN + "COMPILED_BUILD.json")
    require(build["outputs"] == result["served_build_outputs"] and len(build["outputs"]) == 8 and type(build["compiler_exit"]) is int and build["compiler_exit"] == 0, "actual compiled browser build differs")
    for name, digest in build["outputs"].items():
        require(records.sha(G12_RUN + name) == digest, "accepted compiled browser bytes changed")
    for name in ["web/app.ts", "analysis-service/native.ts", "analysis-service/server.ts", "analysis-service/telemetry.ts"]:
        absolute = str(Path(scope["root"]) / name)
        require(build["source_inputs"][absolute] == scope["source_bindings"][absolute], "actual browser compiler source graph differs")
    # Capture provenance is checked through immutable bodies and real stage/log
    # relationships. Native moves, controls and browser actions are not replayed.
    require(result["served_asset_bodies"] == 24 and result["served_compiled_js_bodies"] == 8 and result["native_starts"] == result["native_exits"] == 88 and result["all_processes_closed"] is True, "final browser endpoint or native closure incomplete")
    return {"accepted_independent_result": records.sha(G12_RUN + "independent/FINAL_BROWSER.json"), "served_compiled_js_bodies": 8, "additional_source_inputs": {hook: {"sha256": hashlib.sha256(source_bytes(checkout, hook)).hexdigest(), "mode": "100644"}}, "historical_samples_reexecuted": False}


def verify(bundle, inputs, checkout, expected_commit, gate):
    domain = inputs["domains"][gate]
    require(gate in DRIVERS and domain["driver"] == DRIVERS[gate] and domain["source_commit"] == expected_commit, "unsupported or stale final evidence dispatch")
    require(domain["engine_sha256"] == inputs["engine"]["sha256"] == ENGINE and domain["network_sha256"] == inputs["network"]["artifact"]["sha256"] == NETWORK, "final adapter deployment differs")
    records = Records(bundle, domain, gate)
    details = (g11 if gate == "G11" else g12)(records, checkout)
    return {"status": "passed_final_closed_evidence_adapter", "gate": gate, "full_gate": True, "full_acceptance": False, "coordinator_source_commit": expected_commit, "engine_sha256": ENGINE, "network_sha256": NETWORK, "bound_record_count": len(records.records), "native_starts_in_this_adapter": 0, "browser_starts_in_this_adapter": 0, "original_compiler_runtime_closure": False, **details}


def integrate(bundle, inputs, checkout, expected_commit, review):
    accepted = []
    for gate, driver in DRIVERS.items():
        if inputs["domains"][gate].get("driver") != driver:
            continue
        result = verify(bundle, inputs, checkout, expected_commit, gate)
        review.setdefault("verified_semantic_gates", {})[gate] = result
        review["pending_semantic_gates"].pop(gate)
        accepted.append(gate)
    # Component integration never overrides failed, missing or unavailable gates.
    require(review["full_acceptance"] is False, "partial final integration cannot claim full acceptance")
    if accepted:
        review["final_closed_evidence_integration"] = {
            "gates": accepted,
            "native_starts": 0,
            "browser_starts": 0,
            "closed_semantic_sample_replays": 0,
            "full_acceptance": False,
        }

