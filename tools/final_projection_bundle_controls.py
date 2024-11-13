"""Unexecuted rehashed Bundle controls for a future admitted metadata owner.

No CLI, authority, scope, token or fixture is created on import. The future owner
must independently admit source, seed, operations, clocks, storage and starts.
This helper neither supplies that admission nor invokes a designated entry.
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
CASE_NAMES = (
    "G08_missing_actual_failed_independent_exit",
    "G08_rehashed_hidden_unfinished_outcomes",
    "G10_missing_actual_reused_comparison_stage",
    "G10_rehashed_erased_exhausted_active_time",
    "G15_missing_limited_attribution_report",
    "G15_rehashed_claimed_historical_raw_reconstruction",
    "G08_rehashed_legacy_replay_dispatch",
    "G10_rehashed_stale_domain_source",
    "G14_rehashed_offered_unaccepted_join",
    "G14_rehashed_caller_gate_pass",
    "G16_rehashed_offered_audit_without_external_root",
    "G16_rehashed_caller_release_pass",
)
FORGED_CASE_NAMES = (CASE_NAMES[1], CASE_NAMES[3], CASE_NAMES[5])
NEGATIVE_CASES = len(CASE_NAMES)


def run_controls(seed, fixture, archive, scope, expected_owner_scope_sha256, quota, lease):
    """Copy an admitted seed once, then call actual Bundle projection readers.

    A real future owner must provide an installed specialized Quota and the real
    HostLease. Its separately pinned scope must enumerate every writable path and
    directory, exact seed inventory, source identity and bounded Git commands.
    These conditions are dependencies, not authority conveyed by a caller dict.
    """
    from tools.host_lease import HostLease
    from tools.final_fixture_quota import FixtureQuota
    from verification.bundle import Bundle, strict_json
    from verification.final_gate_decisions import ATTRIBUTION, LINEAGE, NEURAL, NEURAL_STAGE
    from verification.final_projection import CLOSED_GATES, verify
    from verification.source import relative_path, require

    require(type(quota) is FixtureQuota and quota.old is not None
            and isinstance(lease, HostLease) and not lease.stream.closed,
            "real installed fixture quota and live host lease required")
    quota.bind_helper(scope, expected_owner_scope_sha256, "bundle-controls")
    lease.check()
    require(scope["schema"] == "caissa-final-projection-bundle-controls-v1"
            and type(scope["maximum_control_invocations"]) is int
            and scope["maximum_control_invocations"] == 1
            and scope["maximum_projection_calls"] == NEGATIVE_CASES + 1
            and type(scope["deadline_unix"]) in {int, float}
            and math.isfinite(scope["deadline_unix"])
            and scope["origin_unix"] <= time.time() < scope["deadline_unix"]
            <= scope["parent_deadline_unix"]
            and scope["parent_deadline_unix"] > 1793283600.005172,
            "fresh separately admitted finite control scope required")
    seed, fixture, archive = (Path(p).absolute() for p in (seed, fixture, archive))
    require(seed == ROOT / relative_path(scope["seed"])
            and fixture == ROOT / relative_path(scope["fixture"])
            and archive == ROOT / relative_path(scope["case_archive"])
            and all(p == p.resolve() and p.is_relative_to(ROOT / "work")
                    and p != ROOT / "work" for p in (seed, fixture, archive))
            and all(not a.is_relative_to(b) for a in (seed, fixture, archive)
                    for b in (seed, fixture, archive) if a != b)
            and len({seed, fixture, archive}) == 3
            and seed.is_dir() and not fixture.exists() and not archive.exists(),
            "separate real seed and fresh owned fixture/archive paths required")
    require(fixture.is_relative_to(quota.output) and archive.is_relative_to(quota.output),
            "fixture and retained cases must be charged to the installed quota")
    pins = scope["seed_files"]
    require(isinstance(pins, dict) and 3 <= len(pins) <= 1024
            and {"MANIFEST.json", "SOURCE_INPUTS.json", "FULL_INPUTS.json"} <= set(pins)
            and type(scope["maximum_payload_write_bytes"]) is int
            and 0 < scope["maximum_payload_write_bytes"] <= 256 * 1024**2,
            "exact finite seed and payload-write inventory required")
    for name, pin in pins.items():
        relative_path(name)
        require(set(pin) == {"bytes", "sha256"} and type(pin["bytes"]) is int
                and 0 <= pin["bytes"] <= 8 * 1024**2,
                "seed file bound differs")
    require(sum(p["bytes"] for p in pins.values()) <= 64 * 1024**2,
            "seed total metadata-copy bound exceeded")
    state = quota.read()
    require(state["scope_sha256"] == expected_owner_scope_sha256
            and not state["closed"] and state.get("failure") is None,
            "fixture quota scope is closed, failed or different")
    written, calls = 0, 0
    known = {}

    def tick():
        lease.check()
        require(time.time() < scope["deadline_unix"], "control family deadline exhausted")
        current = quota.read()
        require(not current["closed"] and current.get("failure") is None,
                "fixture quota failed or closed during controls")

    def encoded(value):
        return (json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + "\n").encode()

    def write(target, raw, *, fresh=False):
        nonlocal written
        tick()
        require(target == target.resolve() and target.is_relative_to(quota.output)
                and len(raw) <= 8 * 1024**2,
                "control payload path or file bound exceeded")
        written += len(raw)
        require(written <= scope["maximum_payload_write_bytes"],
                "cumulative control payload-write bound exceeded")
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("xb" if fresh else "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        info = target.lstat()
        require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1
                and stat.S_IMODE(info.st_mode) == 0o600,
                "fixture payload must remain private and single-link")
        if target.is_relative_to(fixture):
            name = str(target.relative_to(fixture))
            if name != "MANIFEST.json":
                known[name] = hashlib.sha256(raw).hexdigest()

    def manifest():
        write(fixture / "MANIFEST.json", encoded({"files": known}))

    def reference(name):
        return {"path": name, "sha256": known[name]}

    def project(current):
        nonlocal calls
        tick()
        require(calls < scope["maximum_projection_calls"], "new projection-call bound exhausted")
        calls += 1
        seconds = min(30, scope["deadline_unix"] - time.time())
        # The fixture's input digest is a test input only. It supplies neither
        # authority nor external audit trust. No audit receipt is loaded here.
        return verify(fixture, ROOT, scope["product_commit"],
                      hashlib.sha256(encoded(current)).hexdigest(), seconds)

    os.umask(0o077)
    archive.mkdir()
    write(archive / "STARTED.json", encoded({"owner_scope_sha256": expected_owner_scope_sha256,
          "control_invocations": 1, "full_acceptance": False}), fresh=True)
    fixture.mkdir()
    with Bundle(seed, min(30, scope["deadline_unix"] - time.time())) as source:
        manifest_raw = source.bytes("MANIFEST.json", 8 * 1024**2)
        source.verify_manifest(scope["seed_manifest_sha256"])
        require(source.names() == set(pins), "seed inventory differs from external admission")
        for name, pin in pins.items():
            tick()
            # MANIFEST is intentionally absent from its own identities map.
            raw = manifest_raw if name == "MANIFEST.json" else source.bytes(name, 8 * 1024**2)
            require(len(raw) == pin["bytes"]
                    and hashlib.sha256(raw).hexdigest() == pin["sha256"],
                    "seed differs from its independently pinned bytes: " + name)
            write(fixture / name, raw, fresh=True)
    require(known["FULL_INPUTS.json"] == scope["seed_inputs_sha256"],
            "seed input declaration differs from external identity")
    inputs_raw = (fixture / "FULL_INPUTS.json").read_bytes()
    inputs = strict_json(inputs_raw)
    require(inputs_raw == encoded(inputs), "seed input declaration must have exact control encoding")
    baseline = project(inputs)
    categories = {gate: row["classification"] for gate, row in baseline["gate_decisions"].items()}
    require(set(categories) == {f"G{i:02d}" for i in range(1, 17)}
            and {g for g, c in categories.items() if c == "verified"} == CLOSED_GATES
            and {g: c for g, c in categories.items() if c != "verified"}
            == {"G08": "failed_requirement", "G10": "incomplete", "G14": "unverified",
                "G15": "unavailable_inputs", "G16": "blocked"}
            and baseline["full_acceptance"] is False and baseline["exit_code"] == 2
            and set(baseline["actual_closed_adapter_results"]) == CLOSED_GATES,
            "actual baseline projection did not preserve all sixteen decisions")
    controls = [{"case": "actual_bundle_projection_preserves_all_sixteen_decisions",
                 "passed": True, "report_sha256": hashlib.sha256(encoded(baseline)).hexdigest()}]
    write(archive / "BASELINE.json", encoded(baseline), fresh=True)
    descriptors = {}
    for gate in ("G08", "G10", "G15"):
        name = inputs["domains"][gate]["final_decision_evidence"]["path"]
        require(name == "decisions/" + gate + "/INDEX.json",
                "control descriptor differs from exact mutable writer inventory")
        descriptors[gate] = (name, (fixture / name).read_bytes())

    def reject(name, expected, change):
        require(name == CASE_NAMES[len(controls) - 1], "new control order differs from writer inventory")
        current, changed = copy.deepcopy(inputs), {}
        original_error = None
        try:
            change(current, changed, name)
            write(fixture / "FULL_INPUTS.json", encoded(current))
            manifest()
            # A broken hash or inventory cannot count as the intended rejection.
            with Bundle(fixture, min(30, scope["deadline_unix"] - time.time())) as bundle:
                bundle.verify_manifest()
            try:
                project(current)
            except ValueError as error:
                require(str(error) == expected, "unrelated rejection in case: " + name)
                row = {"case": name, "rejected": True, "reason": str(error),
                       "inputs": current, "changed_descriptors": changed,
                       "manifest": {"files": dict(known)}, "full_acceptance": False}
                write(archive / (name + ".json"), encoded(row), fresh=True)
                controls.append({"case": name, "rejected": True, "reason": str(error)})
            else:
                raise ValueError("new rehashed Bundle forgery accepted: " + name)
        except BaseException as error:
            original_error = error
            raise
        finally:
            try:
                for index_name in changed:
                    original = next(raw for path, raw in descriptors.values() if path == index_name)
                    write(fixture / index_name, original)
                write(fixture / "FULL_INPUTS.json", inputs_raw)
                manifest()
            except BaseException as cleanup_error:
                if original_error is not None:
                    original_error.add_note("fixture restoration also failed: " + type(cleanup_error).__name__)
                else:
                    raise

    def decision_change(gate, logical, *, remove=False, mutate=None):
        def change(current, changed, label):
            index_name, original = descriptors[gate]
            index = strict_json(original)
            require(logical in index["records"], "case requires the real original decision record")
            if remove:
                index["records"].pop(logical)
            else:
                source_name = index["records"][logical]["path"]
                value = strict_json((fixture / source_name).read_bytes())
                mutate(value)
                forged_name = "FORGERIES/" + label + ".json"
                write(fixture / forged_name, encoded(value), fresh=True)
                index["records"][logical] = reference(forged_name)
            write(fixture / index_name, encoded(index))
            changed[index_name] = index
            domain = current["domains"][gate]
            domain.update(final_decision_evidence=reference(index_name),
                          artifacts=[reference(index_name), *index["records"].values()])
        return change

    inventory_error = "nonpassing decision metadata inventory differs"
    fixed_error = "fixed original nonpassing evidence changed: "
    reject("G08_missing_actual_failed_independent_exit", inventory_error,
           decision_change("G08", NEURAL_STAGE, remove=True))
    reject("G08_rehashed_hidden_unfinished_outcomes", fixed_error + NEURAL + "SUMMARY.json",
           decision_change("G08", NEURAL + "SUMMARY.json",
                           mutate=lambda x: x.update(games=4000, unfinished_games=0, complete_sample=True)))
    stage = "runs/full-parallel-strength-v1/attempts/attempt-004/independent-threads-2-ms-100.json"
    reject("G10_missing_actual_reused_comparison_stage", inventory_error,
           decision_change("G10", stage, remove=True))
    usage = "runs/full-parallel-strength-v1/ACTIVE_USAGE.json"
    reject("G10_rehashed_erased_exhausted_active_time", fixed_error + usage,
           decision_change("G10", usage, mutate=lambda x: x.update(active_seconds=0, closed=False)))
    reject("G15_missing_limited_attribution_report", inventory_error,
           decision_change("G15", ATTRIBUTION, remove=True))
    available = LINEAGE + "AVAILABILITY.json"
    reject("G15_rehashed_claimed_historical_raw_reconstruction", fixed_error + available,
           decision_change("G15", available, mutate=lambda x: x.update(full_raw_reproduction_available=True)))
    reject("G08_rehashed_legacy_replay_dispatch",
           "nonpassing decision source, driver or deployment differs",
           lambda x, *_: x["domains"]["G08"].update(driver="strength-journals-v1"))
    reject("G10_rehashed_stale_domain_source", "full gate source identity differs: G10",
           lambda x, *_: x["domains"]["G10"].update(source_commit="0" * 40))
    offered = inputs["domains"]["G08"]["final_decision_evidence"]
    reject("G14_rehashed_offered_unaccepted_join", "unaccepted G14 join artifacts cannot promote the gate",
           lambda x, *_: x["domains"]["G14"].update(
               artifacts=[offered], final_semantic_evidence=offered))
    reject("G14_rehashed_caller_gate_pass", "unaccepted G14 join artifacts cannot promote the gate",
           lambda x, *_: x["domains"]["G14"].update(full_gate=True))
    reject("G16_rehashed_offered_audit_without_external_root",
           "offered audit artifacts have no external trusted receipt",
           lambda x, *_: x["domains"]["G16"].update(
               artifacts=[offered], final_audit_evidence=offered))
    reject("G16_rehashed_caller_release_pass", "empty audit declaration contains unverified pass fields",
           lambda x, *_: x["domains"]["G16"].update(full_acceptance=True))
    require(len(controls) == NEGATIVE_CASES + 1 and calls == NEGATIVE_CASES + 1
            and tuple(row["case"] for row in controls[1:]) == CASE_NAMES
            and (fixture / "FULL_INPUTS.json").read_bytes() == inputs_raw,
            "new control inventory, projection count or restoration differs")
    with Bundle(fixture, min(30, scope["deadline_unix"] - time.time())) as restored:
        restored.verify_manifest()
        for name, pin in pins.items():
            if name != "MANIFEST.json":
                require(restored.sha(name) == pin["sha256"], "baseline copied evidence was not restored")
    with Bundle(seed, min(30, scope["deadline_unix"] - time.time())) as original:
        original.verify_manifest(scope["seed_manifest_sha256"])
        require(original.names() == set(pins), "seed inventory changed during controls")
        for name, pin in pins.items():
            require(original.sha(name) == pin["sha256"], "original seed bytes changed during controls")
    tick()
    return {"status": "passed_new_bundle_controls_component", "controls": controls,
            "actual_projection_calls": calls, "payload_write_bytes": written,
            "seed_bytes_preserved": True, "closed_controls_or_samples_reexecuted": 0,
            "designated_entry_invocations": 0, "full_R12_complete": False, "full_acceptance": False}
