"""Join a new committed source boundary to retained core receipts, metadata only."""

import fcntl
import hashlib
import json
import os
from pathlib import Path
import resource
import signal
import stat
import sys
import time


def main(scope_path):
    scope_path = Path(scope_path).resolve()
    scope = json.loads(scope_path.read_text())
    root, output = Path(scope["root"]), scope_path.parent
    started = time.monotonic()
    assert scope["status"] == "admitted" and time.time() < scope["deadline_unix"]
    assert not (output / "STARTED.json").exists(), "one new join invocation only"
    assert str(Path(sys.executable).resolve()) == scope["interpreter"]
    assert hashlib.sha256(Path(scope["interpreter"]).read_bytes()).hexdigest() == scope["interpreter_sha256"]
    lease = (root / "runs/TIMED_STRENGTH.lock").open("a")
    fcntl.flock(lease.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    resource.setrlimit(resource.RLIMIT_FSIZE, (512000, 512000))
    resource.setrlimit(resource.RLIMIT_CPU, (45, 45))

    def stop(*_):
        raise TimeoutError("new source-identity join deadline exhausted")

    signal.signal(signal.SIGALRM, stop)
    signal.setitimer(signal.ITIMER_REAL, scope["maximum_active_seconds"])

    def audit(event, args):
        if event.startswith("socket.") or event in {"os.system", "os.posix_spawn", "os.exec"}:
            raise RuntimeError("identity join prohibits network and actors")
        if event == "subprocess.Popen":
            executable, argv = args[:2]
            assert Path(executable).name == "git" and len(argv) > 1 and argv[1] in {"ls-tree", "cat-file", "rev-parse", "ls-files"}, "only read-only Git metadata commands are allowed"
        if event == "open":
            name, mode, flags = args
            writing = (isinstance(mode, str) and any(c in mode for c in "wax+")) or (isinstance(flags, int) and flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND))
            if writing:
                if isinstance(name, int):
                    assert stat.S_ISFIFO(os.fstat(name).st_mode), "only Git transport pipes may be opened by descriptor"
                    return
                assert isinstance(name, (str, bytes, os.PathLike)) and Path(name).resolve().is_relative_to(output), "identity join write escaped its output"

    sys.addaudithook(audit)
    (output / "STARTED.json").write_text(json.dumps({"started_unix": time.time()}) + "\n")
    for name, expected in scope["input_bindings"].items():
        assert hashlib.sha256((root / name).read_bytes()).hexdigest() == expected, "pinned join input differs: " + name
    sys.path.insert(0, str(root))
    from verification.runtime_binding import inspect
    from verification.bundle import strict_json

    def document(name):
        assert name in scope["input_bindings"]
        return strict_json((root / name).read_bytes())

    boundary = inspect(
        root,
        scope["product_commit"],
        root / "config/protocol-v4.json",
        scope["input_bindings"]["config/protocol-v4.json"],
        root / "runs/full-parallel-strength-v1/bin/caissa",
        root / "runs/full-parallel-strength-v1/inputs/selected.cai",
        root / scope["learning_receipt"],
    )
    old = document("results/native-source-binding-2026-10-26/ACTUAL_BOUNDARY.json")
    assert old["product_source_commit"] != boundary["product_source_commit"], "this is not a status rerun of the old source boundary"
    assert old["native_source_sha256"] == boundary["native_source_sha256"]
    assert old["native_source_modes"] == boundary["native_source_modes"]
    assert boundary["matched_native_files"] == 69 and boundary["full_gate"] is False
    actor, model = boundary["engine_sha256"], boundary["network_sha256"]
    native = document("results/native-checks-d2-2026-10-25/NATIVE_CHECKS.json")
    restoration = document("results/restoration-full-2026-10-25/RESTORATION_CAMPAIGN.json")
    draw = document("results/draw-history-2026-10-25/independent/DRAW_HISTORY.json")
    search = document("results/search-semantics-2026-10-25/SEARCH_SEMANTICS.json")
    numerical = document("results/precision-v4-2026-10-25/macos/INDEPENDENT.json")
    numerical_source = document("results/precision-v4-2026-10-25/macos/PRECISION.json")
    assert native["rules"]["status"] == "passed" and native["protocol"]["status"] == "passed"
    assert restoration["full_gate"] is True and draw["status"] == "passed" and draw["full_gate"] is True
    assert search["status"] == "passed" and search["full_gate"] is True and search["native_exit"] == 0
    assert search["source_commit"] == boundary["compiled_source_commit"] and search["engine_sha256"] == actor
    assert numerical["status"] == "passed" and numerical["network_sha256"] == model
    assert numerical["engine_sha256"] == numerical_source["engine_sha256"]
    rows = []
    specifications = [
        ("G01", native["rules"], native["scope"]["source_commit"], "rules"),
        ("G02", restoration, restoration["source_commit"], "restoration"),
        ("G03", draw, draw["source_commit"], "draw history"),
        ("G04", native["protocol"], native["scope"]["source_commit"], "protocol"),
        ("G05", search, search["source_commit"], "search semantics"),
        ("G06", numerical, numerical_source["source_commit"], "network numerics"),
    ]
    for gate, receipt, commit, subject in specifications:
        assert receipt["full_acceptance"] is False
        same_actor = receipt["engine_sha256"] == actor
        rows.append({
            "gate": gate,
            "subject": subject,
            "historical_status": receipt.get("status"),
            "historical_source_commit": commit,
            "historical_engine_sha256": receipt["engine_sha256"],
            "same_saved_actor": same_actor,
            "same_network_if_declared": receipt.get("network_sha256") == model if "network_sha256" in receipt else None,
            "identity_join": "same_actor_and_native_source_boundary" if same_actor else "different_historical_actor; final_actor_runtime_missing",
            "historical_receipt_changed": False,
            "new_semantic_execution": False,
            "final_gate_certified": False,
        })
    assert [row["gate"] for row in rows if row["same_saved_actor"]] == ["G05"]
    result = {
        "status": "metadata_identity_join_completed",
        "product_source_commit": scope["product_commit"],
        "compiled_source_commit": boundary["compiled_source_commit"],
        "saved_engine_sha256": actor,
        "saved_network_sha256": model,
        "matched_native_files": boundary["matched_native_files"],
        "domains": rows,
        "original_learning_failures": boundary["original_failed_domains"],
        "original_controller_failure_preserved": native["controller_failure"],
        "scope": "New committed source boundary and six retained core-receipt identities only; no semantic sample rerun",
        "input_sha256": scope["input_bindings"],
        "elapsed_seconds": time.monotonic() - started,
        "native_actors": 0,
        "games": 0,
        "compilations": 0,
        "closed_semantic_samples_reexecuted": 0,
        "original_compiler_runtime_closure_established": False,
        "full_gate": False,
        "full_acceptance": False,
    }
    (output / "BOUNDARY.json").write_text(json.dumps(boundary, indent=2) + "\n")
    (output / "CORE_IDENTITY_JOIN.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({"status": result["status"], "native_files": 69, "same_actor_domains": ["G05"], "elapsed_seconds": result["elapsed_seconds"], "full_acceptance": False}))


if __name__ == "__main__":
    main(sys.argv[1])
