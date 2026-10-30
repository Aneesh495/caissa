"""Finite independent fixture-owner transport and saved-result closure.

No admission, authority or seed is created on import. The external executor must
pin this source and an already admitted scope, review actual human provenance,
account cumulative starts, and independently observe this launcher's own exit.
"""

import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import resource
import selectors
import signal
import stat
import subprocess
import sys
import time


ROOT = Path(__file__).resolve().parents[1]


def require(value, reason):
    if not value:
        raise ValueError(reason)


def read(name, maximum, *, private=False):
    require(isinstance(name, str) and not name.startswith("/") and "\\" not in name
            and 0 < len(name.encode()) <= 4096
            and all(p not in {"", ".", ".."} for p in name.split("/"))
            and all(32 <= ord(c) != 127 for c in name), "unsafe fixture closure input")
    parts = name.split("/")
    directory = os.open(ROOT, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for part in parts[:-1]:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory)
            os.close(directory)
            directory = child
        descriptor = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
        with os.fdopen(descriptor, "rb") as stream:
            before = os.fstat(stream.fileno())
            require(stat.S_ISREG(before.st_mode) and before.st_nlink == 1 and before.st_size <= maximum
                    and (not private or stat.S_IMODE(before.st_mode) == 0o600),
                    "fixture closure input is linked, public or excessive")
            raw = stream.read(maximum + 1)
            after = os.fstat(stream.fileno())
        stamp = lambda s: (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns)
        require(len(raw) == before.st_size and stamp(before) == stamp(after), "fixture closure input changed")
        return raw
    finally:
        os.close(directory)


def encoded(value):
    return (json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n").encode()


def capture(command, *, deadline, hard_deadline, maximum, environment):
    """Own one actual process group and drain both separately bounded pipes."""
    selector = selectors.DefaultSelector()
    process, failure, stopping = None, None, None
    gone, term_sent, kill_sent, exit_observed = False, False, False, None
    retained = {k: bytearray() for k in ("stdout", "stderr")}
    counts, hashes, eof = ({k: 0 for k in retained}, {k: hashlib.sha256() for k in retained},
                          {k: False for k in retained})
    cleanup = []

    def signal_group(sig):
        nonlocal gone
        if gone or process is None:
            return
        try:
            os.killpg(process.pid, 0)
        except ProcessLookupError:
            gone = True
            return
        try:
            os.killpg(process.pid, sig)
        except ProcessLookupError:
            gone = True

    try:
        process = subprocess.Popen(command, cwd=ROOT, stdin=subprocess.DEVNULL,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, bufsize=0,
                                   start_new_session=True, env=environment)
        for label in retained:
            pipe = getattr(process, label)
            os.set_blocking(pipe.fileno(), False)
            selector.register(pipe, selectors.EVENT_READ, label)
        while process.poll() is None or selector.get_map():
            now = time.time()
            if process.poll() is not None and exit_observed is None:
                exit_observed = now
            if now >= deadline and failure is None:
                failure = "owner-or-pipe-deadline"
            if failure is not None and stopping is None:
                stopping = time.monotonic()
            if stopping is not None and not term_sent:
                signal_group(signal.SIGTERM)
                term_sent = True
            if stopping is not None and time.monotonic() - stopping >= 0.5 and not kill_sent:
                signal_group(signal.SIGKILL)
                kill_sent = True
            if now >= hard_deadline - 5:
                failure = failure or "transport-cleanup-window"
                break
            for key, _ in selector.select(0.05):
                try:
                    body = os.read(key.fd, 65536)
                except BlockingIOError:
                    continue
                if not body:
                    eof[key.data] = True
                    selector.unregister(key.fileobj)
                    key.fileobj.close()
                    continue
                counts[key.data] += len(body)
                hashes[key.data].update(body)
                retained[key.data].extend(body[:max(0, maximum - len(retained[key.data]))])
                if counts[key.data] > maximum:
                    failure = failure or "output-bound"
        if process.poll() is None:
            signal_group(signal.SIGKILL)
        process.wait(timeout=max(0.1, min(2, hard_deadline - time.time())))
        exit_observed = exit_observed or time.time()
        if exit_observed > deadline:
            failure = failure or "owner-exit-after-deadline"
        if not gone:
            try:
                os.killpg(process.pid, 0)
            except ProcessLookupError:
                gone = True
            else:
                failure = failure or "group-survived-owner"
                signal_group(signal.SIGTERM)
                until = min(hard_deadline - 2, time.time() + 0.5)
                while not gone and time.time() < until:
                    try:
                        os.killpg(process.pid, 0)
                    except ProcessLookupError:
                        gone = True
                    if not gone:
                        time.sleep(0.02)
                if not gone:
                    signal_group(signal.SIGKILL)
    except BaseException as error:
        failure = failure or type(error).__name__
    finally:
        if process is not None:
            try:
                if process.poll() is None or not gone:
                    signal_group(signal.SIGKILL)
                process.wait(timeout=max(0.1, min(2, hard_deadline - time.time())))
                if not gone:
                    try:
                        os.killpg(process.pid, 0)
                    except ProcessLookupError:
                        gone = True
            except BaseException as error:
                cleanup.append(type(error).__name__)
            for label in retained:
                pipe = getattr(process, label)
                if pipe is not None and not pipe.closed:
                    pipe.close()
        selector.close()
    return {"pid": process.pid if process else None, "exit": process.returncode if process else None,
            "exit_observed_unix": exit_observed,
            "group_absent": gone, "failure": failure, "cleanup_errors": cleanup,
            "streams": {k: {"observed_bytes": counts[k], "retained_bytes": len(retained[k]),
                            "discarded_bytes": counts[k] - len(retained[k]), "eof": eof[k],
                            "observed_sha256": hashes[k].hexdigest()} for k in retained}}, retained


def check_helper(scope, helper, read_output):
    """Independently join actual saved bodies; never accepts an offered pass map."""
    payload = scope["payload"]
    require(helper["full_R12_complete"] is False and helper["full_acceptance"] is False,
            "fixture helper promoted a component")
    if scope["operation"] == "build-seed":
        require(helper["status"] == "built_unaccepted_projection_seed_candidate"
                and helper["seed"] == payload["seed"] and helper["projection_calls"] == 0
                and helper["consumer_admitted"] is False
                and set(helper["seed_files"]) == set(payload["output_files"]),
                "actual seed result differs from the independent admitted inventory")
        catalog = helper["seed_files"]
        names, hashes, total = set(catalog), {}, 0
        require(3 <= len(names) <= 1024, "seed closure inventory exceeded")
        for name, pin in catalog.items():
            body = read_output("output/seed/" + name)
            total += len(body)
            require(total <= payload["maximum_seed_bytes"] and len(body) == pin["bytes"]
                    and hashlib.sha256(body).hexdigest() == pin["sha256"], "actual seed body differs")
            hashes[name] = pin["sha256"]
        manifest = json.loads(read_output("output/seed/MANIFEST.json"))
        inputs = json.loads(read_output("output/seed/FULL_INPUTS.json"))
        require(manifest == {"files": {n: v for n, v in hashes.items() if n != "MANIFEST.json"}}
                and hashes["MANIFEST.json"] == helper["seed_manifest_sha256"]
                and hashes["FULL_INPUTS.json"] == helper["seed_inputs_sha256"]
                and inputs["source_commit"] == scope["product_commit"]
                and all(inputs["domains"][g]["artifacts"] == [] for g in ("G14", "G16")),
                "seed manifest, source, inputs or unaccepted-root declaration differs")
        return {"kind": "unaccepted_seed_candidate", "files": len(names), "payload_bytes": total,
                "seed_manifest_sha256": hashes["MANIFEST.json"], "consumer_admitted": False}
    from tools.final_projection_bundle_controls import CASE_NAMES, FORGED_CASE_NAMES
    require(helper["status"] == "passed_new_bundle_controls_component"
            and helper["actual_projection_calls"] == len(helper["controls"]) == 13
            and helper["seed_bytes_preserved"] is True
            and tuple(row["case"] for row in helper["controls"][1:]) == CASE_NAMES,
            "actual Bundle baseline/case inventory differs")
    baseline = json.loads(read_output("output/cases/BASELINE.json"))
    expected = {f"G{i:02d}": "verified" for i in range(1, 17)}
    expected.update(G08="failed_requirement", G10="incomplete", G14="unverified",
                    G15="unavailable_inputs", G16="blocked")
    require(baseline["exit_code"] == 2 and baseline["full_acceptance"] is False
            and baseline["source_commit"] == scope["product_commit"]
            and {g: r["classification"] for g, r in baseline["gate_decisions"].items()} == expected,
            "actual saved Bundle baseline lost a nonpassing decision")
    seed_names = set(payload["seed_files"]) - {"MANIFEST.json"}
    forged_names = {"FORGERIES/" + n + ".json" for n in FORGED_CASE_NAMES}
    for row in helper["controls"][1:]:
        case = json.loads(read_output("output/cases/" + row["case"] + ".json"))
        require(row["rejected"] is True and case["case"] == row["case"] and case["rejected"] is True
                and case["reason"] == row["reason"] and case["full_acceptance"] is False,
                "actual retained Bundle rejection differs from its helper result")
        snapshot = case["manifest"]["files"]
        require(seed_names <= set(snapshot) <= seed_names | forged_names,
                "retained rejection manifest omitted or added evidence")
        for name, digest in snapshot.items():
            body = (encoded(case["inputs"]) if name == "FULL_INPUTS.json" else
                    encoded(case["changed_descriptors"][name]) if name in case["changed_descriptors"] else
                    read_output("output/fixture/" + name))
            require(hashlib.sha256(body).hexdigest() == digest, "retained Bundle snapshot digest differs")
    for name, pin in payload["seed_files"].items():
        if name != "MANIFEST.json":
            require(hashlib.sha256(read_output("output/fixture/" + name)).hexdigest() == pin["sha256"],
                    "actual copied seed payload was not restored")
    return {"kind": "actual_baseline_and_rehashed_Bundle_controls", "controls": 13,
            "baseline_exit": 2, "nonpassing_categories_preserved": True}


def run(scope_name, expected_scope_sha256, verified_human_message_sha256):
    started = time.monotonic()
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    hard = resource.getrlimit(resource.RLIMIT_CPU)[1]
    cpu = 30 if hard == resource.RLIM_INFINITY else min(30, hard)
    require(cpu > 0, "fixture launcher inherited CPU limit exhausted")
    resource.setrlimit(resource.RLIMIT_CPU, (cpu, cpu))
    hard = resource.getrlimit(resource.RLIMIT_FSIZE)[1]
    size = 8 * 1024**2 if hard == resource.RLIM_INFINITY else min(8 * 1024**2, hard)
    require(size >= 1024**2, "fixture launcher inherited file limit insufficient")
    resource.setrlimit(resource.RLIMIT_FSIZE, (size, size))
    signal.signal(signal.SIGALRM, lambda *_: (_ for _ in ()).throw(TimeoutError("fixture launcher fixed deadline")))
    signal.setitimer(signal.ITIMER_REAL, 150)
    require(sys.dont_write_bytecode and sys.flags.safe_path and Path.cwd().resolve() == ROOT,
            "fixture launcher needs safe admitted Python startup")
    raw = read(scope_name, 1024**2, private=True)
    require(hashlib.sha256(raw).hexdigest() == expected_scope_sha256, "fixture launcher independent scope pin differs")
    scope = json.loads(raw)
    for name in ("tools/final_fixture_launcher.py", "tools/final_fixture_admission.py",
                 "tools/parallel_storage_quota.py", "tools/storage_budget.py"):
        require(hashlib.sha256(read(name, 4 * 1024**2)).hexdigest() == scope["source_bindings"][name],
                "fixture launcher bootstrap source changed")

    def reject_cache(event, args):
        if event == "open" and isinstance(args[0], str) and args[0].endswith(".pyc"):
            if Path(args[0]).absolute().is_relative_to(ROOT):
                raise FileNotFoundError("fixture launcher requires pinned project source")

    sys.addaudithook(reject_cache)
    sys.path.insert(0, str(ROOT))
    from tools.final_fixture_admission import document, owner_limits, relative
    from tools.parallel_storage_quota import check_admission
    from tools.storage_budget import footprint
    import shutil
    scope = document(raw)
    owner_limits(scope)
    require(scope["schema"] == "caissa-final-fixture-owner-scope-v1" and scope["status"] == "admitted"
            and scope["maximum_launcher_cpu_seconds"] <= cpu and scope["python_command"] == sys.executable
            and scope["python_prefix"] == sys.prefix and str(Path(sys.executable).resolve()) == scope["interpreter"]
            and Path(sys.executable).stat().st_size <= 32 * 1024**2
            and hashlib.sha256(Path(sys.executable).read_bytes()).hexdigest() == scope["interpreter_sha256"],
            "fixture launcher admission or resource identity differs")
    human = document(read(scope["authority_path"], 16384, private=True))
    require(hashlib.sha256(read(scope["authority_path"], 16384, private=True)).hexdigest() == scope["authority_sha256"]
            and hashlib.sha256(human["literal_user_message"].encode()).hexdigest() == verified_human_message_sha256
            == scope["verified_human_message_sha256"]
            and time.time() < scope["deadline_unix"] < scope["launcher_hard_deadline_unix"]
            <= human["deadline_unix"] == scope["parent_deadline_unix"], "fixture launcher actual human window differs")
    resource.setrlimit(resource.RLIMIT_CPU, (scope["maximum_launcher_cpu_seconds"],) * 2)
    signal.setitimer(signal.ITIMER_REAL, scope["launcher_hard_deadline_unix"] - time.time())
    owner_work, launch_name = relative(scope["work"]), relative(scope["launcher_work"])
    launch = ROOT / launch_name
    require(launch == launch.resolve() and not launch.exists(), "fixture launcher namespace already consumed")
    with (ROOT / "runs/TIMED_STRENGTH.lock").open("rb") as probe:
        fcntl.flock(probe, fcntl.LOCK_EX | fcntl.LOCK_NB)
        fcntl.flock(probe, fcntl.LOCK_UN)
    inventory_raw = read(scope["external_inventory_path"], 16384, private=True)
    require(hashlib.sha256(inventory_raw).hexdigest() == scope["external_inventory_sha256"]
            and document(inventory_raw)["paths"] == scope["external_paths"], "fixture launcher attribution differs")
    actual = footprint([ROOT, *scope["external_paths"]])
    check_admission(actual["charged_bytes"], shutil.disk_usage(ROOT).used, scope["data_bytes"],
                    sum(scope[k] for k in ("control_bytes", "outside_control_bytes", "launcher_control_bytes",
                                          "launcher_outside_control_bytes")), 128000000)
    os.umask(0o077)
    launch.mkdir()
    command = [scope["python_command"], "-B", "-P", str(ROOT / "tools/final_fixture_owner.py"),
               "--scope", scope_name, "--expected-scope-sha256", expected_scope_sha256,
               "--verified-human-message-sha256", verified_human_message_sha256]
    names = {"STARTED.json", "owner.stdout", "owner.stderr", "CLOSED.json", "FAILED.json"}
    writes, spent, spawns = set(), 0, []

    def audit(event, args):
        if event.startswith("socket.") or event in {
            "os.system", "os.posix_spawn", "os.exec", "os.fork", "os.forkpty", "os.link", "os.symlink",
            "os.remove", "os.rename", "os.mkdir", "os.rmdir", "os.truncate", "os.chmod", "os.chown", "os.utime"
        }:
            raise ValueError("fixture launcher rejects network and unrelated mutation")
        if event == "subprocess.Popen":
            require(args[1] == command and not spawns, "fixture launcher permits one exact owner")
            spawns.append(True)
        if event == "open":
            name, mode, flags = args
            writing = isinstance(mode, str) and any(c in mode for c in "wax+") or (
                isinstance(flags, int) and flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND))
            if writing and name != os.devnull:
                require(isinstance(name, str) and Path(name).absolute().parent == launch
                        and Path(name).name in names and flags & os.O_EXCL and flags & os.O_CREAT,
                        "fixture launcher writer escaped exact exclusive outputs")

    sys.addaudithook(audit)

    def put(name, body):
        nonlocal spent
        require(name in names and name not in writes and len(body) <= 512000
                and spent + len(body) <= scope["launcher_control_bytes"], "fixture launcher credits exhausted")
        writes.add(name)
        spent += len(body)
        with (launch / name).open("xb") as stream:
            stream.write(body)
            stream.flush()
            os.fsync(stream.fileno())

    observed, result = None, None
    try:
        put("STARTED.json", encoded({"scope_sha256": expected_scope_sha256, "launcher_pid": os.getpid()}))
        env = {k: v for k, v in os.environ.items() if k not in {"CAISSA_HOST_LEASE_FD", "CAISSA_FINAL_ENTRY_TOKEN_FD"}}
        observed, retained = capture(command, deadline=scope["deadline_unix"],
                                     hard_deadline=scope["launcher_hard_deadline_unix"],
                                     maximum=scope["maximum_owner_output_bytes"], environment=env)
        for key, body in retained.items():
            put("owner." + key, bytes(body))
        require(observed["exit"] == 0 and observed["failure"] is None and observed["group_absent"]
                and not observed["cleanup_errors"] and len(spawns) == 1
                and observed["streams"]["stderr"]["observed_bytes"] == 0
                and all(row["eof"] and row["discarded_bytes"] == 0 for row in observed["streams"].values()),
                "fixture actual owner exit, complete transport or group closure failed")
        summary = document(bytes(retained["stdout"]))
        used = 0

        def bounded(name, maximum, *, private=True):
            nonlocal used
            body = read(name, maximum, private=private)
            used += len(body)
            require(used <= scope["maximum_launcher_pin_read_bytes"], "fixture closure read allowance exhausted")
            return body

        saved = {name: bounded(owner_work + "/" + name, 1024**2)
                 for name in ("OWNER_STARTED.json", "HELPER_RESULT.json", "OWNER_RESULT.json", "WRITE_USAGE.json")}
        require(summary["status"] == "completed_fixture_component_self_report"
                and summary["scope_sha256"] == expected_scope_sha256
                and summary["post_cleanup_sha256"] == {n: hashlib.sha256(b).hexdigest() for n, b in saved.items()}
                and summary["owner_exit_independently_checked"] is False and summary["final_group_check_pending"] is True
                and summary["full_R12_complete"] is False and summary["full_acceptance"] is False,
                "actual captured fixture summary differs from post-cleanup files")
        started_owner, helper, owner, ledger = (document(saved[n]) for n in
                                               ("OWNER_STARTED.json", "HELPER_RESULT.json", "OWNER_RESULT.json", "WRITE_USAGE.json"))
        require(started_owner["owner_pid"] == started_owner["owner_group"] == observed["pid"]
                and started_owner["owner_start"] == 1 and started_owner["scope_sha256"] == expected_scope_sha256
                and owner["scope_sha256"] == expected_scope_sha256
                and owner["helper_result_sha256"] == hashlib.sha256(saved["HELPER_RESULT.json"]).hexdigest()
                and ledger["scope_sha256"] == expected_scope_sha256 and ledger["closed"] is True
                and ledger.get("failure") is None and ledger.get("owner_failure") is None
                and not ledger["cleanup_errors"], "actual fixture owner/result/closed ledger differs")
        rows = owner["git_commands"]
        require(len(rows) == scope["maximum_source_git_commands"] and all(
            row["ordinal"] == i + 1 and row["kind"] == ("head", "tree", "blobs")[i % 3]
            and row["exit"] == 0 and row["owner_group_id"] == observed["pid"]
            and row["inherited_owner_group"] is True and all(row["eof"].values())
            and not any(row["discarded_bytes"].values()) and row["observed_bytes"]["stderr"] == 0
            and not row["cleanup_errors"] for i, row in enumerate(rows)), "actual fixture source Git closure differs")
        for row in rows[::3]:
            require(row["observed_sha256"]["stdout"] == hashlib.sha256((scope["product_commit"] + "\n").encode()).hexdigest(),
                    "actual source Git HEAD output differs")

        def output(name):
            return bounded(owner_work + "/" + name, scope["writer_file_bounds"][name])

        for name, pin in scope["source_bindings"].items():
            require(hashlib.sha256(read(name, 4 * 1024**2)).hexdigest() == pin, "fixture source changed after owner")
        for name, pin in scope["input_bindings"].items():
            require(hashlib.sha256(bounded(name, 16 * 1024**2, private=False)).hexdigest() == pin, "fixture original input changed")
        proof = check_helper(scope, helper, output)
        require(hashlib.sha256(read(scope_name, 1024**2, private=True)).hexdigest() == expected_scope_sha256,
                "fixture immutable scope changed")
        with (ROOT / "runs/TIMED_STRENGTH.lock").open("rb") as probe:
            fcntl.flock(probe, fcntl.LOCK_EX | fcntl.LOCK_NB)
            fcntl.flock(probe, fcntl.LOCK_UN)
        own, child = (resource.getrusage(k) for k in (resource.RUSAGE_SELF, resource.RUSAGE_CHILDREN))
        family_cpu = own.ru_utime + own.ru_stime + child.ru_utime + child.ru_stime
        require(family_cpu <= scope["maximum_launcher_family_cpu_seconds"]
                and time.time() < scope["launcher_hard_deadline_unix"] and time.monotonic() - started <= 150,
                "fixture launcher closure exhausted its fixed bounds")
        result = {"schema": "caissa-independent-fixture-owner-closure-v1", "status": "passed_fixture_owner_closure_component",
                  "scope_sha256": expected_scope_sha256, "owner_exit": 0, "transport": observed,
                  "post_cleanup_sha256": summary["post_cleanup_sha256"], "helper": proof,
                  "observed_self_and_reaped_child_cpu_seconds": family_cpu, "closed": True,
                  "host_lease_free": True, "launcher_exit_independently_checked": False,
                  "full_R12_complete": False, "full_acceptance": False}
        put("CLOSED.json", encoded(result))
    except BaseException as error:
        put("FAILED.json", encoded({"scope_sha256": expected_scope_sha256, "failure_type": type(error).__name__,
                                    "reason": str(error)[:2048], "transport": observed,
                                    "closed": True, "full_acceptance": False}))
        raise
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
    return {"status": result["status"], "owner_exit": 0, "helper": result["helper"],
            "launcher_exit_independently_checked": False, "full_R12_complete": False, "full_acceptance": False}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--scope", required=True)
    parser.add_argument("--expected-scope-sha256", required=True)
    parser.add_argument("--verified-human-message-sha256", required=True)
    args = parser.parse_args()
    try:
        value = run(args.scope, args.expected_scope_sha256, args.verified_human_message_sha256)
    except Exception as error:
        print(json.dumps({"status": "rejected", "error_type": type(error).__name__, "full_acceptance": False}))
        raise SystemExit(1)
    print(json.dumps(value, allow_nan=False))
