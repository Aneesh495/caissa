"""Unexecuted saved-evidence seed builder for a future admitted metadata owner.

No CLI, scope/authority writer, verifier dispatch or work on import. A built seed
is an unaccepted candidate. Its producer inventory cannot admit its own consumer.
"""

import copy
import hashlib
import json
import math
import os
from pathlib import Path
import stat
import time


ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = "runs/final-lineage-adapter-2026-10-29/fixture"
TEMPLATE_COMMIT = "1e89d2b9ce1038bcceb40cf08754dfaa877ec6de"


def build_seed(scope, expected_owner_scope_sha256, quota, lease):
    """Build only under a separately admitted real owner and installed quota.

    The missing admission/fixture owner must first verify actual human renewal,
    scope/source/interpreter identities, all input pins, finite counters/clocks,
    storage including nineteen external paths and every permitted operation.
    This function does not infer those permissions from its configuration.
    """
    from tools.host_lease import HostLease
    from tools.parallel_storage_quota import Quota
    from verification.bundle import Bundle, digest_text, strict_json
    from verification.final_audit_bundle import DRIVER as AUDIT_DRIVER
    from verification.final_evidence_bundle import ENGINE, NETWORK
    from verification.final_gate_decisions import DRIVERS, POLICY, POLICY_SHA256
    from verification.final_projection import CLOSED_DRIVERS, CLOSED_GATES
    from verification.final_projection_entry import private_bytes
    from verification.final_semantic_bundle import DRIVER as SEMANTIC_DRIVER
    from verification.source import PRODUCT, relative_path, require, verify_checkout

    require(isinstance(quota, Quota) and quota.old is not None
            and isinstance(lease, HostLease) and not lease.stream.closed,
            "seed building needs the real installed quota and live host lease")
    require(scope["schema"] == "caissa-final-projection-seed-build-v1"
            and type(scope["maximum_seed_builds"]) is int and scope["maximum_seed_builds"] == 1
            and type(scope["maximum_projection_calls"]) is int and scope["maximum_projection_calls"] == 0
            and type(scope["deadline_unix"]) in {int, float}
            and math.isfinite(scope["deadline_unix"])
            and scope["origin_unix"] <= time.time() < scope["deadline_unix"]
            <= scope["parent_deadline_unix"]
            and scope["parent_deadline_unix"] > 1793283600.005172,
            "fresh finite separately admitted seed-building scope required")
    template = ROOT / TEMPLATE
    seed_name = relative_path(scope["seed"])
    seed = ROOT / seed_name
    require(template == template.resolve() and template.is_dir()
            and seed == seed.resolve() and seed.is_relative_to(ROOT / "work")
            and seed != ROOT / "work" and seed.is_relative_to(quota.output)
            and not seed.exists() and not seed.is_relative_to(template)
            and not template.is_relative_to(seed),
            "seed needs a fresh owned work destination separate from the retained template")
    pins = scope["template_files"]
    require(isinstance(pins, dict) and 3 <= len(pins) <= 1024
            and {"MANIFEST.json", "SOURCE_INPUTS.json", "FULL_INPUTS.json"} <= set(pins),
            "exact externally pinned retained-template inventory required")
    for name, pin in pins.items():
        relative_path(name)
        require(set(pin) == {"bytes", "sha256"} and type(pin["bytes"]) is int
                and 0 <= pin["bytes"] <= 8 * 1024**2,
                "retained-template file bound differs")
        digest_text(pin["sha256"])
    require(sum(pin["bytes"] for pin in pins.values()) <= 64 * 1024**2,
            "retained template exceeds the metadata-copy ceiling")
    source_name = relative_path(scope["source_inventory_input"])
    require(source_name.startswith(".agent-local/"), "separate private current-source input required")
    digest_text(scope["source_inventory_sha256"])
    require(type(scope["maximum_seed_bytes"]) is int
            and 0 < scope["maximum_seed_bytes"] <= 64 * 1024**2,
            "finite seed payload reservation required")
    read_total, written, seed_pins = 0, 0, {}

    def tick():
        lease.check()
        require(time.time() < scope["deadline_unix"], "seed-build family deadline exhausted")
        state = quota.read()
        require(state["scope_sha256"] == expected_owner_scope_sha256
                and not state["closed"] and state.get("failure") is None,
                "seed-build quota is closed, failed or bound to another owner")

    def encoded(value):
        return (json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n").encode()

    def account(raw):
        nonlocal read_total
        read_total += len(raw)
        require(read_total <= 72 * 1024**2, "seed pinned input-payload read ceiling exceeded")

    def read(bundle, name, pin):
        tick()
        raw = bundle.bytes(name, 8 * 1024**2)
        account(raw)
        require(len(raw) == pin["bytes"]
                and hashlib.sha256(raw).hexdigest() == pin["sha256"],
                "seed input differs from its external pin or aggregate ceiling: " + name)
        return raw

    def write(name, raw):
        nonlocal written
        tick()
        require(name in names and name not in seed_pins and len(raw) <= 8 * 1024**2,
                "seed output is undeclared, repeated or excessive")
        written += len(raw)
        require(written <= scope["maximum_seed_bytes"], "admitted seed payload bytes exhausted")
        target = seed / name
        require(target == target.resolve() and target.is_relative_to(seed), "seed writer escaped")
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("xb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        info = target.lstat()
        require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1
                and stat.S_IMODE(info.st_mode) == 0o600,
                "seed output is linked or public")
        seed_pins[name] = {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}

    tick()
    source_raw = private_bytes(source_name, 4 * 1024**2)
    account(source_raw)
    require(hashlib.sha256(source_raw).hexdigest() == scope["source_inventory_sha256"],
            "externally pinned source-inventory bytes changed")
    source_document = strict_json(source_raw)
    # Exactly the existing read-only rev-parse, ls-tree and cat-file commands.
    # The future builder owner must admit/count these, separately from entry.
    verify_checkout(ROOT, source_document, scope["product_commit"], PRODUCT)
    tick()
    with Bundle(ROOT, min(30, scope["deadline_unix"] - time.time())) as retained:
        policy_raw = retained.bytes(POLICY)
        account(policy_raw)
        require(hashlib.sha256(policy_raw).hexdigest() == POLICY_SHA256,
                "fixed nonpassing-decision policy changed")
        policy = strict_json(policy_raw)
        require(policy["schema"] == "caissa-frozen-nonpassing-decision-policy-v1"
                and policy["execution_authority"] is False
                and set(policy["gates"]) == set(DRIVERS),
                "decision policy is not the fixed non-authorizing declaration")
        original_pins = {}
        for gate in sorted(DRIVERS):
            for logical, pin in policy["gates"][gate]["records"].items():
                relative_path(logical)
                require(logical not in original_pins or original_pins[logical] == pin,
                        "overlapping decision records disagree")
                original_pins[logical] = pin
        require(scope["decision_records"] == original_pins
                and sum(p["bytes"] for p in original_pins.values()) <= 4 * 1024**2,
                "independently admitted decision-input inventory differs from fixed policy")
        copied = set(pins) - {"MANIFEST.json", "FULL_INPUTS.json", "SOURCE_INPUTS.json"}
        decision_paths = {n: "decisions/retained/" + n for n in original_pins}
        indexes = {g: "decisions/" + g + "/INDEX.json" for g in DRIVERS}
        generated = {"MANIFEST.json", "FULL_INPUTS.json", "SOURCE_INPUTS.json",
                     *decision_paths.values(), *indexes.values()}
        require(not copied & generated, "seed generated namespace collides with retained evidence")
        names = copied | generated
        require(len(names) <= 1024 and set(scope["output_files"]) == names
                and len(scope["output_files"]) == len(names),
                "exact finite seed writer inventory required")
        prefixes = {}
        for name in names:
            parts = relative_path(name).split("/")
            for end in range(1, len(parts) + 1):
                prefix = "/".join(parts[:end])
                folded = prefix.casefold()
                require(folded not in prefixes or prefixes[folded] == prefix,
                        "seed names alias on the case-insensitive filesystem")
                prefixes[folded] = prefix
                if end < len(parts):
                    require(prefix not in names, "seed file also names an ancestor directory")
        os.umask(0o077)
        seed.mkdir()
        with Bundle(template, min(30, scope["deadline_unix"] - time.time())) as old:
            manifest_raw = old.bytes("MANIFEST.json", 8 * 1024**2)
            account(manifest_raw)
            require(hashlib.sha256(manifest_raw).hexdigest() == pins["MANIFEST.json"]["sha256"]
                    == scope["template_manifest_sha256"]
                    and len(manifest_raw) == pins["MANIFEST.json"]["bytes"],
                    "retained template manifest differs from external admission")
            old.verify_manifest(scope["template_manifest_sha256"])
            require(old.names() == set(pins), "retained template has extra or missing files")
            inputs = None
            for name, pin in pins.items():
                if name == "MANIFEST.json":
                    continue
                raw = read(old, name, pin)
                if name == "FULL_INPUTS.json":
                    require(pin["sha256"] == scope["template_inputs_sha256"],
                            "retained template full-input identity differs")
                    inputs = strict_json(raw)
                elif name != "SOURCE_INPUTS.json":
                    write(name, raw)
            require(inputs["schema"] == "caissa-full-inputs-v1"
                    and inputs["source_commit"] == TEMPLATE_COMMIT
                    and set(inputs["domains"]) == {f"G{i:02d}" for i in range(1, 17)}
                    and inputs["engine"]["sha256"] == ENGINE
                    and inputs["network"]["artifact"]["sha256"] == NETWORK,
                    "retained template source, deployment or gate inventory differs")
            inputs = copy.deepcopy(inputs)
            inputs["source_commit"] = scope["product_commit"]
            require(set(CLOSED_DRIVERS) == CLOSED_GATES, "closed-adapter driver map is incomplete")
            for gate in CLOSED_DRIVERS:
                domain = inputs["domains"][gate]
                require(domain["driver"] == CLOSED_DRIVERS[gate] and domain["artifacts"]
                        and domain["source_commit"] == TEMPLATE_COMMIT,
                        "retained closed-adapter declaration differs")
                # Original evidence bodies retain their historical source fields.
                # Only this new coordinator's domain declaration changes here.
                domain["source_commit"] = scope["product_commit"]
        for logical, pin in original_pins.items():
            write(decision_paths[logical], read(retained, logical, pin))
        reference = lambda name: {"path": name, "sha256": seed_pins[name]["sha256"]}
        for gate in sorted(DRIVERS):
            records = {logical: reference(decision_paths[logical])
                       for logical in policy["gates"][gate]["records"]}
            write(indexes[gate], encoded({"schema": "caissa-frozen-nonpassing-records-v1",
                                        "gate": gate, "records": records}))
            inputs["domains"][gate] = {
                "source_commit": scope["product_commit"], "driver": DRIVERS[gate],
                "engine_sha256": ENGINE, "network_sha256": NETWORK,
                "final_decision_evidence": reference(indexes[gate]),
                "artifacts": [reference(indexes[gate]), *records.values()]}
        for gate, driver in [("G14", SEMANTIC_DRIVER), ("G16", AUDIT_DRIVER)]:
            inputs["domains"][gate] = {
                "source_commit": scope["product_commit"], "driver": driver,
                "engine_sha256": ENGINE, "network_sha256": NETWORK, "artifacts": []}
        write("SOURCE_INPUTS.json", source_raw)
        write("FULL_INPUTS.json", encoded(inputs))
        write("MANIFEST.json", encoded({"files": {n: p["sha256"] for n, p in seed_pins.items()}}))
    require(set(seed_pins) == names, "built seed writer inventory is incomplete")
    with Bundle(seed, min(30, scope["deadline_unix"] - time.time())) as built:
        built.verify_manifest(seed_pins["MANIFEST.json"]["sha256"])
        require(built.names() == names, "built seed contains unexpected artifacts")
    tick()
    return {"status": "built_unaccepted_projection_seed_candidate",
            "seed": seed_name, "seed_files": seed_pins,
            "seed_manifest_sha256": seed_pins["MANIFEST.json"]["sha256"],
            "seed_inputs_sha256": seed_pins["FULL_INPUTS.json"]["sha256"],
            "payload_bytes_written": written, "pinned_input_payload_bytes_read": read_total,
            "decision_inventory_records": {g: len(policy["gates"][g]["records"]) for g in DRIVERS},
            "projection_calls": 0, "semantic_sample_or_closed_control_replays": 0,
            "consumer_admitted": False, "full_R12_complete": False, "full_acceptance": False}
