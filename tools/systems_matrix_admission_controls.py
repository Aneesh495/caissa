"""Synthetic admission controls only, with no games or raw sample replay."""

import copy
import fcntl
import hashlib
import json
import os
from pathlib import Path
import resource
import signal
import sys
import time


def main(scope_path):
    scope_path = Path(scope_path).resolve()
    scope = json.loads(scope_path.read_text())
    output = scope_path.parent
    root = Path(scope["root"])
    started = time.monotonic()
    lease = (root / "runs/TIMED_STRENGTH.lock").open("a")
    fcntl.flock(lease.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    assert scope["status"] == "admitted"
    assert time.time() < scope["deadline_unix"]
    assert str(Path(sys.executable).resolve()) == scope["interpreter"]
    assert not (output / "STARTED.json").exists(), "one invocation only"
    for name, expected in scope["source_bindings"].items():
        assert hashlib.sha256((root / name).read_bytes()).hexdigest() == expected
    assert hashlib.sha256(Path(scope["interpreter"]).read_bytes()).hexdigest() == scope["interpreter_sha256"]
    (output / "STARTED.json").write_text(json.dumps({"started_unix": time.time()}))
    resource.setrlimit(resource.RLIMIT_FSIZE, (65536, 65536))
    resource.setrlimit(resource.RLIMIT_CPU, (15, 15))

    def timeout(*_):
        raise TimeoutError("new admission-control deadline exhausted")

    signal.signal(signal.SIGALRM, timeout)
    signal.setitimer(signal.ITIMER_REAL, scope["maximum_active_seconds"])

    def audit(event, args):
        if event.startswith("subprocess.") or event.startswith("socket.") or event in {"os.system", "os.posix_spawn", "os.exec"}:
            raise RuntimeError("controls prohibit producers and network access")
        if event == "open":
            name, mode, flags = args
            writing = (isinstance(mode, str) and any(x in mode for x in "wax+")) or (isinstance(flags, int) and flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND))
            if writing:
                assert isinstance(name, (str, bytes, os.PathLike)) and Path(name).resolve().is_relative_to(output), "control write escaped output"

    sys.addaudithook(audit)
    sys.path.insert(0, str(root))
    from verification.bundle import Bundle
    from verification.strength_bundle import stage_campaign
    from verification.systems_bundle import PROFILES, admit
    from verification.systems_strength import BASE, schedule

    identities, matrices = {}, []

    def ref(name, digest=None):
        digest = digest or hashlib.sha256(name.encode()).hexdigest()
        identities[name] = digest
        return {"path": name, "sha256": digest}

    for kind, profile_sha in PROFILES.items():
        matrices.append({
            "kind": kind,
            "profile": ref(kind + "/PROFILE.json", profile_sha),
            "campaigns": [{"comparison": row["id"], "config": ref(kind + "/" + row["id"] + "/CONFIG.json")} for row in schedule(kind)],
        })
    artifacts = [matrix["profile"] for matrix in matrices] + [row["config"] for matrix in matrices for row in matrix["campaigns"]]
    inputs = {"protocol": {"sha256": BASE}, "domains": {"G10": {"systems_strength": {"matrices": matrices}, "artifacts": artifacts}}}
    fixture = output / "fixture"
    fixture.mkdir()
    completed = []
    with Bundle(fixture, maximum_seconds=scope["maximum_active_seconds"]) as bundle:
        bundle.identities = identities

        def check(name, mutate=None):
            assert time.time() < scope["deadline_unix"]
            candidate = copy.deepcopy(inputs)
            if mutate is not None:
                mutate(candidate)
                try:
                    admit(bundle, candidate)
                except (ValueError, KeyError, TypeError):
                    completed.append({"name": name, "status": "rejected_as_required"})
                else:
                    raise AssertionError("malformed inventory admitted: " + name)
            else:
                observed, declared = admit(bundle, candidate)
                assert len(observed) == 2 and len(declared) == 48
                completed.append({"name": name, "status": "admitted_exact_synthetic_inventory"})

        def inventory(value):
            return value["domains"]["G10"]["systems_strength"]["matrices"]

        check("exact_6_plus_40_schedule")
        check("omitted_matrix", lambda v: inventory(v).pop())
        check("reordered_matrices", lambda v: inventory(v).reverse())
        check("duplicate_kind", lambda v: inventory(v)[1].update(kind="parallel"))
        check("extra_descriptor_field", lambda v: inventory(v)[0].update(extra=True))
        check("wrong_protocol", lambda v: v["protocol"].update(sha256="0" * 64))
        check("wrong_profile", lambda v: inventory(v)[0]["profile"].update(sha256="0" * 64))
        check("missing_comparison", lambda v: inventory(v)[0]["campaigns"].pop())
        check("reordered_comparisons", lambda v: inventory(v)[0]["campaigns"].reverse())
        check("typed_comparison_mismatch", lambda v: inventory(v)[0]["campaigns"][0].update(comparison=True))
        check("aliased_config", lambda v: inventory(v)[0]["campaigns"][1].update(config=inventory(v)[0]["campaigns"][0]["config"]))
        check("undeclared_config", lambda v: v["domains"]["G10"]["artifacts"].pop())
        check("manifest_digest_mismatch", lambda v: inventory(v)[0]["campaigns"][0]["config"].update(sha256="0" * 64))
        check("unsafe_reference", lambda v: inventory(v)[0]["campaigns"][0]["config"].update(path="../CONFIG.json"))
        raw = b'{"config":{"pairs":1}}\n'
        missing = fixture / "missing"
        missing.mkdir()
        (missing / "CONFIG.json").write_bytes(raw)
        digest = hashlib.sha256(raw).hexdigest()
        bundle.identities = {"missing/CONFIG.json": digest}
        destination = output / "must-not-stage"
        try:
            stage_campaign(bundle, {"config": {"path": "missing/CONFIG.json", "sha256": digest}}, set(bundle.identities), destination, 1)
        except ValueError as error:
            assert str(error) == "strength raw campaign inventory is missing, extra or undeclared"
            assert not destination.exists()
            completed.append({"name": "missing_raw_inventory_rejected_before_staging", "status": "rejected_as_required"})
        else:
            raise AssertionError("partial raw inventory admitted")
    assert len(completed) == 15
    result = {"status": "passed", "scope": "Synthetic adapter import, exact schedule admission and malformed/partial inventory rejection only", "controls": completed, "elapsed_seconds": time.monotonic() - started, "real_games": 0, "native_actors": 0, "raw_campaign_replays": 0, "actual_full_bundle_acceptance": False, "full_G10_certified": False, "full_acceptance": False, "old_scope_reopened": False}
    (output / "RESULT.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({"status": result["status"], "controls": len(completed), "elapsed_seconds": result["elapsed_seconds"]}))


if __name__ == "__main__":
    main(sys.argv[1])
