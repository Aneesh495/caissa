"""Inspect the exact closed macOS G14 archive without rerunning its tests."""

import fcntl
import hashlib
import io
import json
import os
from pathlib import Path
import resource
import signal
import stat
import subprocess
import sys
import threading
import time
import zipfile


def require(value, reason):
    if not value:
        raise ValueError(reason)


def main(path):
    started = time.monotonic()
    os.umask(0o077)
    path = Path(path).resolve()
    scope = json.loads(path.read_text())
    root, output = Path(scope["root"]), path.parent
    require(scope["status"] == "admitted" and time.time() < scope["deadline_unix"] <= scope["parent_deadline_unix"] and not (output / "STARTED.json").exists(), "one fresh finite G14 archive inspection required")
    lease = (root / "runs/TIMED_STRENGTH.lock").open("r+")
    fcntl.flock(lease, fcntl.LOCK_EX | fcntl.LOCK_NB)
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    resource.setrlimit(resource.RLIMIT_CPU, (90, 90))
    resource.setrlimit(resource.RLIMIT_FSIZE, (8 * 1024**2, 8 * 1024**2))
    def stop(*_):
        raise TimeoutError("finite G14 archive inspection deadline exhausted")
    signal.signal(signal.SIGALRM, stop)
    signal.setitimer(signal.ITIMER_REAL, min(180, scope["deadline_unix"] - time.time()))
    command = [scope["gh"], "api", "repos/Aneesh495/caissa/actions/artifacts/12655115593/zip"]
    commands, destinations, charged = [], set(), {"raw": 0, "control": 0}
    def audit(event, args):
        if event.startswith("socket.") or event in {"os.system", "os.posix_spawn", "os.exec", "os.link", "os.symlink", "os.remove", "os.rename"}:
            raise ValueError("only one exact owned G14 archive transport admitted")
        if event == "subprocess.Popen":
            require(args[1] == command and not commands, "G14 archive command/start differs")
            commands.append(command)
        if event == "open":
            name, mode, flags = args
            writing = isinstance(mode, str) and any(c in mode for c in "wax+") or isinstance(flags, int) and flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND)
            if writing:
                if isinstance(name, int):
                    require(stat.S_ISFIFO(os.fstat(name).st_mode), "only owned G14 transport pipes admitted")
                else:
                    p = Path(name).absolute()
                    require(p == p.resolve() and p.is_relative_to(output) and not p.exists() and str(p) not in destinations, "immutable G14 archive output escaped or was rewritten")
                    require(p.is_relative_to(output / "raw") or p.is_relative_to(output / "records") or p.parent == output and p.suffix == ".json", "unknown G14 archive writer")
                    destinations.add(str(p))
                    require(len(destinations) <= 96, "G14 retained file count exceeded")
        if event == "os.mkdir":
            require(Path(args[0]).absolute().resolve().is_relative_to(output), "G14 archive directory escaped")
    sys.addaudithook(audit)
    def put(relative, raw):
        p = output / relative
        p.parent.mkdir(parents=True, exist_ok=True)
        kind = "raw" if relative.startswith("raw/") else "control"
        charged[kind] += ((max(1, len(raw)) + 4095) // 4096) * 4096 + 4096
        require(charged[kind] <= scope[kind + "_bytes"], "G14 prepaid output allowance exhausted")
        p.write_bytes(raw)
    def document(relative, value):
        put(relative, (json.dumps(value, indent=2, sort_keys=True) + "\n").encode())
    document("STARTED.json", {"unix": time.time()})
    require(str(Path(sys.executable).resolve()) == scope["interpreter"] and hashlib.sha256(Path(sys.executable).read_bytes()).hexdigest() == scope["interpreter_sha256"], "G14 archive interpreter differs")
    for name, digest in scope["input_bindings"].items():
        p = root / name
        require(p.resolve() == p and p.is_file() and hashlib.sha256(p.read_bytes()).hexdigest() == digest, "G14 archive source/input differs: " + name)
    expected = scope["artifact"]
    require(expected["id"] == 12655115593 and expected["size_in_bytes"] == 54893531 and expected["digest"] == "sha256:45dd6642b18d9535e6e851c1d3f05231d6f950e4173013d33e7b56633c2fc0b3" and expected["expired"] is False and expected["workflow_run"]["head_sha"] == "1deecce362cf12d9758e1af4bbebb5bbdda95fb1", "G14 live archive identity differs")
    buffer, digest, size = io.BytesIO(), hashlib.sha256(), 0
    env = dict(os.environ, GH_NO_UPDATE_NOTIFIER="1", GH_NO_EXTENSION_UPDATE_NOTIFIER="1", GH_PROMPT_DISABLED="1")
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env, start_new_session=True)
    error_count, error_sha = [0], hashlib.sha256()
    def drain():
        while block := process.stderr.read(16384):
            error_count[0] += len(block)
            error_sha.update(block)
    reader = threading.Thread(target=drain, daemon=True)
    reader.start()
    try:
        while block := process.stdout.read(65536):
            size += len(block)
            require(size <= expected["size_in_bytes"] <= 64 * 1024**2, "G14 compressed transport ceiling exhausted")
            digest.update(block)
            buffer.write(block)
        require(process.wait(timeout=10) == 0 and size == expected["size_in_bytes"] and "sha256:" + digest.hexdigest() == expected["digest"], "actual G14 transport/digest differs")
    finally:
        if process.poll() is None:
            os.killpg(process.pid, signal.SIGTERM)
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait(timeout=2)
        reader.join(timeout=2)
        require(not reader.is_alive(), "G14 stderr pipe survived")
        process.stdout.close()
        process.stderr.close()
        try:
            os.killpg(process.pid, 0)
        except ProcessLookupError:
            absent = True
        else:
            absent = False
        document("TRANSPORT.json", {"exit": process.returncode, "stderr_bytes": error_count[0], "stderr_sha256": error_sha.hexdigest(), "owned_group_absent_after_reap": absent})
    require(error_count[0] == 0 and absent, "G14 transport stderr or cleanup differs")
    buffer.seek(0)
    with zipfile.ZipFile(buffer) as archive:
        entries = archive.infolist()
        require(0 < len(entries) <= 20000 and len({x.filename for x in entries}) == len(entries) and sum(x.file_size for x in entries) <= 1024**3, "G14 archive inventory exceeds bound")
        require(all(not x.filename.startswith("/") and ".." not in Path(x.filename).parts and not stat.S_ISLNK(x.external_attr >> 16) and not x.flag_bits & 1 for x in entries), "unsafe G14 archive member")
        def entry(suffix, maximum=1024**2):
            found = [x for x in entries if x.filename == suffix or x.filename.endswith("/" + suffix)]
            require(len(found) == 1 and found[0].file_size <= maximum, "G14 compact member missing/ambiguous/oversized: " + suffix)
            return found[0]
        def read(suffix):
            return json.loads(archive.read(entry(suffix)))
        config_entry = entry("original-witness/CONFIG.json")
        prefix = config_entry.filename[:-len("CONFIG.json")]
        original = [x for x in entries if x.filename.startswith(prefix) and not x.is_dir()]
        require(0 < len(original) <= 65 and sum(x.file_size for x in original) <= 8 * 1024**2, "original G14 raw witness bound differs")
        pins = {}
        for item in original:
            name = item.filename[len(prefix):]
            raw = archive.read(item)
            require(len(raw) == item.file_size, "original G14 member length differs")
            put("raw/" + name, raw)
            pins[name] = hashlib.sha256(raw).hexdigest()
        manifest = json.loads((output / "raw/MANIFEST.json").read_text())
        require(manifest["files"] == {n: h for n, h in pins.items() if n != "MANIFEST.json"}, "original G14 positive manifest differs")
        config = json.loads((output / "raw/CONFIG.json").read_text())
        require(config["source_commit"] == expected["workflow_run"]["head_sha"] and pins["engine"] == config["engine_sha256"] == "1ff25a97b2272f589aac40049f9c76e53228a3682f64489c72566dae449a9897" and pins["network.cai"] == config["network_sha256"] == "52d0306143392ad683c3ebb09fe013f34e1f9e2bc44d3aa153b32314207374b7", "original G14 actor/source differs")
        result = read("positive-full-entry-replay/G14/G14.json")
        require(result["status"] == "passed" and result["full_gate"] is True and result["full_acceptance"] is False and result["original_manifest_sha256"] == pins["MANIFEST.json"] and result["engine_sha256"] == pins["engine"] and result["network_sha256"] == pins["network.cai"], "actual original independent G14 result differs")
        controls = read("CONTROLS.json")
        require(controls["status"] == "passed" and controls["full_G14_saved_image_sample"] is True and controls["semantic_rehashed_rejections"] == 16 and len(controls["full_entry_cases"]) == 7 and controls["strength_games"] == 0 and controls["training"] is False and controls["browser"] is False, "actual original G14 control closure differs")
        document("records/ORIGINAL_G14.json", result)
        document("records/ORIGINAL_CONTROLS.json", controls)
        case_rows = []
        for case in ["positive-full-entry", "missing-replay-output", "illegal-pv", "swapped-result-colors", "mismatched-network-inference", "incorrect-draw-claim", "undeclared-raw-artifact"]:
            observed = read(case + "-RESULT.json")
            code = 2 if case in {"positive-full-entry", "missing-replay-output"} else 1
            require(type(observed["exit"]) is int and observed["exit"] == code and observed["stderr"] == "" and observed["stdout"]["full_acceptance"] is False and observed["ordinary_manifest_and_external_pin_recomputed"] is True, "actual original G14 full-entry exit differs")
            if case == "positive-full-entry":
                require(observed["stdout"]["verified_semantic_gates"]["G14"] == result and len(observed["stdout"]["pending_semantic_gates"]) == 15, "actual original G14 positive full entry differs")
            elif code == 1:
                require(observed["stdout"]["status"] == "rejected", "original semantic negative case was not rejected")
            document("records/" + case + "-RESULT.json", observed)
            case_rows.append({"case": case, "exit": code})
        require(case_rows == controls["full_entry_cases"], "original actual full-entry inventory differs")
        rejection_manifests = []
        families = ["illegal-pv", "swapped-result-colors", "mismatched-network-inference", "incorrect-draw-claim"]
        require([(x["family"], x["variant"]) for x in result["rehashed_semantic_rejections"]] == [(f, v) for f in families for v in range(4)], "original G14 rejection schedule differs")
        for row in result["rehashed_semantic_rejections"]:
            item = entry("positive-full-entry-replay/G14/audit/" + row["family"] + "-" + str(row["variant"]) + "/MANIFEST.json")
            raw = archive.read(item)
            require(hashlib.sha256(raw).hexdigest() == row["rehashed_manifest_sha256"], "original negative witness manifest differs")
            negative = json.loads(raw)["files"]
            parent = item.filename[:-len("MANIFEST.json")]
            members = [x for x in entries if x.filename.startswith(parent) and not x.is_dir() and x.filename != item.filename]
            require({x.filename[len(parent):] for x in members} == set(negative) and len(members) <= 64 and sum(x.file_size for x in members) <= 8 * 1024**2, "original negative witness inventory differs")
            for member in members:
                require(hashlib.sha256(archive.read(member)).hexdigest() == negative[member.filename[len(parent):]], "original negative witness raw bytes differ")
            rejection_manifests.append({"family": row["family"], "variant": row["variant"], "manifest_sha256": row["rehashed_manifest_sha256"], "files": len(members), "bytes": sum(x.file_size for x in members), "recorded_rejection": row["rejection"]})
        document("records/REJECTION_MANIFESTS.json", rejection_manifests)
        final = {"status": "passed_pinned_G14_archive_inspection", "artifact_id": expected["id"], "archive_bytes": size, "archive_sha256": digest.hexdigest(), "archive_staged_on_filesystem": False, "raw_positive_files": len(pins), "raw_positive_sha256": pins, "original_independent_result_sha256": hashlib.sha256((output / "records/ORIGINAL_G14.json").read_bytes()).hexdigest(), "original_saved_image_sample_passed": True, "original_rehashed_manifests_and_raw_files_checked": 16, "original_full_entry_cases_checked": 7, "old_tests_or_controls_reexecuted": 0, "native_starts": 0, "games": 0, "full_G14_current_source_join": False, "full_R12_complete": False, "full_acceptance": False, "elapsed_seconds": time.monotonic() - started}
        document("RESULT.json", final)
        document("METADATA_USAGE.json", {"closed": True, "failure": None, "raw_reserved_bytes": charged["raw"], "control_reserved_before_ledger_bytes": charged["control"], "native_starts": 0, "owned_fetches": 1, "scope_sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
        print(json.dumps({k: final[k] for k in ["status", "archive_bytes", "raw_positive_files", "old_tests_or_controls_reexecuted", "native_starts", "elapsed_seconds", "full_acceptance"]}))
    buffer.close()


if __name__ == "__main__":
    main(sys.argv[1])
