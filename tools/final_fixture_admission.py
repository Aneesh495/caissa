"""Unexecuted fixture-scope constructor, not a human-approval authority.

No CLI or work on import. A trusted future caller must independently verify the
actual human reply and pin its digest and this request before calling construct.
This source creates no renewal, parent deadline, owner, token, seed or control.
"""

import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import stat
import sys
import time


ROOT = Path(__file__).resolve().parents[1]
EXPIRED_PARENT = 1793283600.005172
REQUIRED_SOURCES = {
    "tools/final_fixture_admission.py", "tools/final_projection_seed.py",
    "tools/final_projection_bundle_controls.py", "tools/host_lease.py",
    "tools/parallel_storage_quota.py", "tools/storage_budget.py",
    "verification/final_projection.py", "verification/final_projection_entry.py",
    "verification/final_gate_decisions.py", "verification/final_semantic_bundle.py",
    "verification/final_audit_bundle.py", "verification/final_audit_trust.py",
    "verification/final_core_bundle.py", "verification/final_evidence_bundle.py",
    "verification/full_bundle.py", "verification/bundle.py", "verification/source.py",
    "config/final-gate-decisions-v1.json",
}


def require(value, reason):
    if not value:
        raise ValueError(reason)


def relative(name):
    require(isinstance(name, str) and 0 < len(name.encode()) <= 4096
            and not name.startswith("/") and "\\" not in name
            and all(p not in {"", ".", ".."} for p in name.split("/"))
            and all(32 <= ord(c) != 127 for c in name), "invalid admission input name")
    return name


def digest(value):
    require(isinstance(value, str) and re.fullmatch("[0-9a-f]{64}", value),
            "invalid independently supplied admission digest")
    return value


def document(raw):
    def pairs(items):
        value = {}
        for key, item in items:
            require(key not in value, "duplicate admission object key")
            value[key] = item
        return value
    def bad(_):
        raise ValueError("nonfinite admission JSON")
    def floating(value):
        number = float(value)
        require(math.isfinite(number), "nonfinite admission JSON")
        return number
    return json.loads(raw, object_pairs_hook=pairs, parse_constant=bad, parse_float=floating)


def stable(name, maximum, *, private=False):
    parts = relative(name).split("/")
    directory = os.open(ROOT, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for part in parts[:-1]:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory)
            os.close(directory)
            directory = child
        fd = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
        with os.fdopen(fd, "rb") as stream:
            before = os.fstat(stream.fileno())
            require(stat.S_ISREG(before.st_mode) and before.st_nlink == 1
                    and 0 <= before.st_size <= maximum
                    and (not private or stat.S_IMODE(before.st_mode) == 0o600),
                    "admission input is linked, public or excessive")
            raw = stream.read(maximum + 1)
            after = os.fstat(stream.fileno())
        stamp = lambda s: (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns)
        require(len(raw) == before.st_size and stamp(before) == stamp(after),
                "admission input changed during descriptor read")
        return raw
    finally:
        os.close(directory)


def runtime_digest(path, maximum):
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(descriptor, "rb") as stream:
        before = os.fstat(stream.fileno())
        require(stat.S_ISREG(before.st_mode) and 0 < before.st_size <= maximum,
                "admission runtime executable is missing or excessive")
        raw = stream.read(maximum + 1)
        after = os.fstat(stream.fileno())
    stamp = lambda s: (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns)
    require(len(raw) == before.st_size and stamp(before) == stamp(after),
            "admission runtime executable changed during read")
    return hashlib.sha256(raw).hexdigest()


def observe_free_lease():
    descriptor = os.open(ROOT / "runs/TIMED_STRENGTH.lock", os.O_RDONLY | os.O_NOFOLLOW)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        fcntl.flock(descriptor, fcntl.LOCK_UN)
    finally:
        os.close(descriptor)


def construct(request_name, expected_request_sha256, verified_human_message_sha256):
    """Write at most one fixture-owner scope after trusted external human review.

    The independent message digest must come from actual direct human input in
    the trusted caller's context. Neither a request field, file, heartbeat, tool
    acknowledgement nor this function can establish that human provenance.
    Bootstrap CPU/wall/output limits and a bounded owned tool transport remain
    the trusted caller's responsibility; this function launches no process.
    """
    started = time.monotonic()
    require(sys.dont_write_bytecode and sys.flags.safe_path and Path.cwd().resolve() == ROOT,
            "fixture admission needs safe pinned Python startup")
    require(relative(request_name).startswith(".agent-local/"), "private independent request required")
    raw = stable(request_name, 1024**2, private=True)
    require(hashlib.sha256(raw).hexdigest() == digest(expected_request_sha256),
            "request differs from independent admission pin")
    request = document(raw)
    require(request["schema"] == "caissa-final-fixture-admission-request-v1"
            and request["operation"] in {"build-seed", "bundle-controls"}
            and request["root"] == str(ROOT), "unsupported fixture admission request")
    authority_name = relative(request["authority_path"])
    require(authority_name.startswith(".agent-local/"), "separate private human provenance required")
    authority_raw = stable(authority_name, 16384, private=True)
    require(hashlib.sha256(authority_raw).hexdigest() == digest(request["authority_sha256"]),
            "human provenance record changed")
    authority = document(authority_raw)
    require(authority["schema"] == "caissa-direct-human-metadata-renewal-v1"
            and authority["scope"] == "saved-evidence-metadata-only"
            and isinstance(authority["literal_user_message"], str)
            and authority["literal_user_message"].strip()
            and hashlib.sha256(authority["literal_user_message"].encode()).hexdigest()
            == digest(verified_human_message_sha256),
            "literal human message differs from independently reviewed direct input")
    now = time.time()
    for value in (authority["received_unix"], authority["deadline_unix"],
                  request["origin_unix"], request["deadline_unix"]):
        require(type(value) in {int, float} and math.isfinite(value), "invalid fixed admission time")
    require(EXPIRED_PARENT < authority["received_unix"] <= request["origin_unix"] <= now
            < request["deadline_unix"] <= authority["deadline_unix"]
            and 0 < authority["deadline_unix"] - authority["received_unix"] <= 7200
            and 0 < request["deadline_unix"] - request["origin_unix"] <= 150,
            "expired parents or scheduled messages cannot renew fixture admission")
    require(type(request["maximum_owner_starts"]) is int and request["maximum_owner_starts"] == 1
            and type(request["maximum_owner_cpu_seconds"]) is int
            and 0 < request["maximum_owner_cpu_seconds"] <= 90,
            "one finite future metadata owner required")
    for name in ("native_starts", "browser_starts", "compiler_starts", "training_starts",
                 "inference_starts", "game_starts", "new_parallel_starts", "extra_parallel_active_seconds",
                 "designated_entry_starts"):
        require(type(request[name]) is int and request[name] == 0,
                "fixture admission cannot authorize actors, matches or a designated entry")
    expected_git = 3 if request["operation"] == "build-seed" else 39
    require(type(request["maximum_source_git_commands"]) is int
            and request["maximum_source_git_commands"] == expected_git,
            "separate exact source-command budget required")
    observe_free_lease()
    require(request["python_command"] == sys.executable and request["python_prefix"] == sys.prefix
            and request["interpreter"] == str(Path(sys.executable).resolve())
            and runtime_digest(Path(sys.executable).resolve(), 32 * 1024**2)
            == digest(request["interpreter_sha256"]), "fixture admission interpreter differs")
    git = shutil.which("git")
    require(git is not None and str(Path(git).resolve()) == request["git_executable"]
            and runtime_digest(Path(git).resolve(), 64 * 1024**2) == digest(request["git_sha256"]),
            "fixture admission resolved Git identity differs")
    work_name = relative(request["work"])
    work = ROOT / work_name
    require(len(work_name.split("/")) == 2 and work_name.startswith("work/")
            and work == work.resolve() and not work.exists(), "fresh once-only work namespace required")
    source_pins, input_pins = request["source_bindings"], request["input_bindings"]
    require(isinstance(source_pins, dict) and REQUIRED_SOURCES <= set(source_pins)
            and len(source_pins) <= 512 and isinstance(input_pins, dict)
            and 0 < len(input_pins) <= 1024, "bounded exact source and input inventories required")
    for pins, maximum, total_bound in [(source_pins, 4 * 1024**2, 32 * 1024**2),
                                       (input_pins, 16 * 1024**2, 64 * 1024**2)]:
        total = 0
        for name, expected in pins.items():
            require(not relative(name).startswith(work_name + "/"), "scope cannot pin its own future outputs")
            body = stable(name, maximum)
            total += len(body)
            require(total <= total_bound and hashlib.sha256(body).hexdigest() == digest(expected),
                    "admission source/input bytes or total ceiling differ: " + name)
    inventory_name = relative(request["external_inventory_path"])
    require(inventory_name.startswith(".agent-local/"), "private separately reviewed attribution required")
    inventory_raw = stable(inventory_name, 16384, private=True)
    require(hashlib.sha256(inventory_raw).hexdigest() == digest(request["external_inventory_sha256"]),
            "external attribution inventory differs")
    inventory = document(inventory_raw)
    external = request["external_paths"]
    require(inventory["schema"] == "caissa-external-attribution-inventory-v1"
            and inventory["paths"] == external and isinstance(external, list)
            and len(external) == len(set(external)) == 19
            and all(isinstance(p, str) and Path(p).is_absolute() and "\0" not in p for p in external),
            "exact separately reviewed nineteen-path attribution required")
    # Completeness must be independently reviewed. A list length is not that review.
    from tools.parallel_storage_quota import check_admission
    from tools.storage_budget import footprint

    for key in ("data_bytes", "control_bytes", "outside_control_bytes", "emergency_control_bytes"):
        require(type(request[key]) is int and request[key] >= 0, "invalid numeric storage reservation")
    require(0 < request["control_bytes"] <= 64000000
            and 0 < request["emergency_control_bytes"] <= request["control_bytes"]
            and request["outside_control_bytes"] >= 4000000
            and type(request["reserve_bytes"]) is int and request["reserve_bytes"] == 128000000,
            "exact finite fixture/control/outside/emergency/reserve peak required")
    payload = request["payload"]
    expected_schema = ("caissa-final-projection-seed-build-v1" if request["operation"] == "build-seed"
                       else "caissa-final-projection-bundle-controls-v1")
    require(isinstance(payload, dict) and payload["schema"] == expected_schema
            and payload["product_commit"] == request["product_commit"]
            and payload["origin_unix"] == request["origin_unix"]
            and payload["deadline_unix"] == request["deadline_unix"]
            and payload["parent_deadline_unix"] == authority["deadline_unix"]
            and re.fullmatch("[0-9a-f]{40}", request["product_commit"]),
            "future helper payload must retain the externally fixed source and human window")
    scope = {**request, "schema": "caissa-final-fixture-owner-scope-v1", "status": "admitted",
             "request_path": request_name, "request_sha256": expected_request_sha256,
             "verified_human_message_sha256": verified_human_message_sha256,
             "parent_deadline_unix": authority["deadline_unix"],
             "constructor_invocations": 1, "full_R12_complete": False, "full_acceptance": False}
    scope_raw = (json.dumps(scope, sort_keys=True, indent=2, allow_nan=False) + "\n").encode()
    require(len(scope_raw) <= 1024**2 and time.time() < request["deadline_unix"]
            and time.monotonic() - started <= 40, "bounded admission preflight exhausted")
    actual = footprint([ROOT, *external])
    check_admission(actual["charged_bytes"], shutil.disk_usage(ROOT).used, request["data_bytes"],
                    request["control_bytes"] + request["outside_control_bytes"] + 2000000, 128000000)
    require(time.time() < request["deadline_unix"] and time.monotonic() - started <= 40,
            "admission deadline exhausted before growth")
    observe_free_lease()
    os.umask(0o077)
    work.mkdir()
    target = work / "SCOPE.json"
    # The only new regular-file output, bounded and prepaid before creation.
    # Failed/partial writes stay retained. This constructor never deletes or starts.
    with target.open("xb") as stream:
        stream.write(scope_raw)
        stream.flush()
        os.fsync(stream.fileno())
    require(stable(work_name + "/SCOPE.json", 1024**2, private=True) == scope_raw,
            "immutable constructed scope readback differs")
    return {"scope": work_name + "/SCOPE.json", "scope_sha256": hashlib.sha256(scope_raw).hexdigest(),
            "request_sha256": expected_request_sha256, "owner_started": False,
            "seed_created": False, "controls_run": 0, "full_R12_complete": False,
            "full_acceptance": False}
