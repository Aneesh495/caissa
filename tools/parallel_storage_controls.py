"""Finite synthetic integration controls, with no game or engine execution."""

import argparse
from contextlib import closing, contextmanager
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def rejected(call):
    try:
        call()
    except ValueError:
        return
    raise AssertionError("control did not reject")


def writer(spec_path, number):
    spec = json.loads(Path(spec_path).read_text())
    quota = load(Path(__file__).with_name("parallel_storage_quota.py"), "quota_writer")
    q = quota.Quota(spec)
    q.install()
    try:
        path = Path(spec["output"]) / f"matches/threads-2-ms-100/games/0000{number:02d}-0.json"
        path.write_bytes(b"x" * 50000)
    except quota.StorageLimit:
        return 3
    return 0


def sleeper():
    child = subprocess.Popen([sys.executable, "-B", "-c", "import time;time.sleep(30)"])

    def stop(*unused):
        child.terminate()
        child.wait(timeout=2)
        raise SystemExit(0)
    signal.signal(signal.SIGTERM, stop)
    print(json.dumps({"descendant": child.pid}), flush=True)
    time.sleep(30)


def controls(scope_path):
    scope = json.loads(scope_path.read_text())
    root = Path(scope["root"])
    for name, pin in scope["sources"].items():
        assert digest(root / name) == pin
    assert time.time() < scope["deadline_unix"] and scope["native_engine_invocations"] == 0
    archive = root / "runs/full-parallel-strength-v1/source"
    sys.path.insert(0, str(archive))
    from tools.host_lease import HostLease
    from tools.campaign_process import Campaign, StageFailure
    from training.corpus import atomic_json
    from arena.run import write_pgn
    qmodule = load(root / "tools/parallel_storage_quota.py", "quota_control")
    resume = load(root / "tools/parallel_storage_resume.py", "resume_control")
    output = Path(scope["output"])
    output.mkdir(parents=True, exist_ok=False)
    usage_path = root / "runs/full-parallel-strength-v1/ACTIVE_USAGE.json"
    before = usage_path.read_bytes()
    tests = []
    index = 0

    def spec(data=8_000_000, control=2_000_000):
        nonlocal index
        index += 1
        folder = output / str(index)
        (folder / "matches/threads-2-ms-100/games").mkdir(parents=True)
        (folder / "matches/threads-2-ms-100/pairs").mkdir()
        return {"output": str(folder), "ledger": str(output / f"ledger-{index}.json"),
                "scope_sha256": digest(scope_path), "deadline_unix": scope["deadline_unix"],
                "data_bytes": data, "control_bytes": control, "reserve_bytes": 128_000_000,
                "immutable_root_names": ["SCOPE.json"]}

    @contextmanager
    def installed(settings):
        quota = qmodule.Quota(settings)
        quota.create()
        quota.install()
        try:
            yield quota
        finally:
            quota.uninstall()

    with closing(HostLease(root / "runs")) as lease:
        rejected(lambda: qmodule.check_admission(4_900_000_000, 1, 100_000_001, 0, 0))
        rejected(lambda: qmodule.check_admission(1, 399_999_999_999, 2, 0, 0))
        assert usage_path.read_bytes() == before
        tests.append("admission rejects before original active ledger is opened")

        settings = spec()
        folder = Path(settings["output"])
        record = {"initial": "8/8/8/8/8/8/8/K6k w - - 0 1", "moves": [],
                  "result": "1/2-1/2", "termination": "synthetic-control", "opening_id": "fixture", "payload": "x" * 160000}
        path = folder / "matches/threads-2-ms-100/games/000000-0.json"
        with installed(settings) as quota:
            atomic_json(path, record)
            write_pgn(record, [{"name": "fixture-a"}, {"name": "fixture-b"}], path)
            atomic_json(folder / "matches/threads-2-ms-100/pairs/000000.json", {"games": [record, record]})
            assert json.loads(path.read_text()) == record and path.with_suffix(".pgn").exists()
            assert quota.read()["data_used"] >= sum(p.stat().st_size for p in folder.rglob("*") if p.is_file())
            pin = digest(path)
            rejected(lambda: path.write_text("overwrite"))
            rejected(lambda: atomic_json(path, {"changed": True}))
            assert digest(path) == pin
        tests.append("actual archived JSON/PGN/pair writers and immutable committed games")

        settings = spec(data=100000)
        quota = qmodule.Quota(settings)
        quota.create()
        sp = output / "concurrent-spec.json"
        sp.write_text(json.dumps(settings))
        children = [subprocess.Popen([sys.executable, "-B", "-P", str(Path(__file__).resolve()),
                    "--writer", str(sp), "--number", str(n)], stdout=subprocess.PIPE, stderr=subprocess.PIPE) for n in (1, 2)]
        exits = []
        for child in children:
            stdout, stderr = child.communicate(timeout=10)
            assert not stdout and not stderr
            exits.append(child.returncode)
        assert sorted(exits) == [0, 3] and quota.read()["data_used"] <= settings["data_bytes"]
        tests.append("separate processes share one durable byte ceiling")

        settings = spec(control=300000)
        folder = Path(settings["output"])
        with installed(settings) as quota:
            for i in range(20):
                atomic_json(folder / "PROGRESS.json", {"iteration": i, "payload": "x" * 10000})
            state = quota.read()
            assert state["control_used"] >= 2 * 10000 and state["control_used"] < 300000
            with (folder / "stage.log").open("wb") as stream:
                stream.writelines([b"a" * 1000, b"b" * 1000])
        tests.append("atomic control replacement peak and parent binary log/writelines are reserved")

        settings = spec(data=75000)
        folder = Path(settings["output"])
        path = folder / "matches/threads-2-ms-100/games/000000-0.json"
        with installed(settings) as quota:
            with path.open("wb") as stream:
                rejected(lambda: stream.write(b"x" * 100000))
                assert path.stat().st_size == 0
                rejected(lambda: stream.buffer)
                rejected(lambda: stream.raw)
                rejected(lambda: stream.detach())
                rejected(lambda: os.write(stream.fileno(), b"bypass"))
                rejected(lambda: stream.truncate(5000000))
                stream.seek(5000000)
                rejected(lambda: stream.write(b"sparse"))
            rejected(lambda: os.open(folder / "RAW.log", os.O_CREAT | os.O_WRONLY, 0o600))
        tests.append("oversized bytes, raw descriptors, raw buffers and sparse growth cannot bypass quota")

        settings = spec()
        folder = Path(settings["output"])
        outside = output / "outside.txt"
        outside.write_text("preserve")
        (folder / "linked.log").symlink_to(outside)
        with installed(settings):
            rejected(lambda: outside.write_text("escape"))
            rejected(lambda: (folder / "linked.log").write_text("escape"))
        assert outside.read_text() == "preserve"
        tests.append("escaped and linked destinations preserve their targets")

        settings = spec(control=100000)
        folder = Path(settings["output"])
        with installed(settings):
            rejected(lambda: atomic_json(folder / "PROGRESS.json", {"payload": "x" * 1000}))
            assert not (folder / "PROGRESS.json.tmp").exists()
        tests.append("atomic temporary-file headroom is rejected before file creation")

        settings = spec(control=5000000)
        folder = Path(settings["output"])
        with installed(settings):
            started = time.monotonic()

            def guard():
                if time.monotonic() - started > 0.4:
                    raise qmodule.StorageLimit("synthetic administrative storage stop")
            campaign = Campaign(folder / "attempts/attempt-005", {}, 10, resource_guard=guard)
            try:
                try:
                    campaign.run("storage-fixture", [sys.executable, "-B", "-P", str(Path(__file__).resolve()), "--sleeper"], 8)
                except StageFailure as error:
                    assert "resource-guard" in error.record["reason"] and error.record["exit"] is not None
                    descendant = json.loads((campaign.output / "storage-fixture.log").read_text())["descendant"]
                    try:
                        os.kill(descendant, 0)
                    except ProcessLookupError:
                        pass
                    else:
                        raise AssertionError("owned descendant remained alive")
                else:
                    raise AssertionError("campaign did not reject quota failure")
            finally:
                campaign.close("expected synthetic storage rejection")
        tests.append("actual archived Campaign terminates and reaps owned process group on storage failure")

        bad = output / "draft.json"
        bad.write_text(json.dumps({"root": str(root), "status": "draft", "deadline_unix": time.time() + 10}))
        rejected(lambda: resume.validate(bad))
        bad.write_text(json.dumps({"root": str(root), "status": "admitted", "deadline_unix": 0}))
        rejected(lambda: resume.validate(bad))
        tests.append("draft and expired continuation reject without admitting an owner")

        settings = spec()
        folder = Path(settings["output"])
        (folder / "source").symlink_to(archive, target_is_directory=True)
        match = folder / "matches/threads-2-ms-100"
        fixture = {"pair": 0, "opening_id": "synthetic-fixture", "games": [
            {"candidate_color": color, "result": "1/2-1/2", "termination": "synthetic-control"}
            for color in ("white", "black")]}
        (match / "pairs/000000.json").write_text(json.dumps(fixture))
        (match / "CONFIG.json").write_text(json.dumps({"config": {"profile": "synthetic-storage-control"}}))
        child_scope = output / "child-scope.json"
        child_spec = {**settings, "root": str(root), "status": "admitted", "effective_attempt": 5,
                      "extra_active_seconds": 0, "source_bindings": {
                          name: digest(root / name) for name in scope["sources"]}}
        child_scope.write_text(json.dumps(child_spec))
        child_spec["scope_sha256"] = digest(child_scope)
        child_quota = qmodule.Quota(child_spec)
        child_quota.create()
        process = subprocess.run([sys.executable, "-B", "-P", str(root / "tools/parallel_storage_resume.py"),
                                 "--scope", str(child_scope), "--stage", "arena.statistics", "--", str(match)],
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=15,
                                 env=lease.environment(), pass_fds=(lease.stream.fileno(),))
        assert process.returncode == 0, process.stderr.decode()
        assert not process.stderr
        assert json.loads((match / "SUMMARY.json").read_text())["profile"] == "synthetic-storage-control"
        assert child_quota.read()["control_used"] > 0
        tests.append("actual child bootstrap inherits exclusive lease and meters the archived summary writer")

        settings = spec(control=2000000)
        settings["deadline_unix"] = time.time() - 1
        folder = Path(settings["output"])
        with installed(settings) as quota:
            rejected(lambda: atomic_json(folder / "PROGRESS.json", {"late": True}))
            atomic_json(folder / "ACTIVE_USAGE.json", {"closed": True, "synthetic": True})
            atomic_json(folder / "FAILED-1.json", {"reason": "synthetic expired deadline"})
            assert json.loads((folder / "ACTIVE_USAGE.json").read_text())["closed"]
            assert quota.read()["data_used"] == 0
        tests.append("expired write deadline still permits bounded emergency active-ledger closure without producer writes")
        assert usage_path.read_bytes() == before
    return {"passed": True, "controls": tests, "real_games": 0,
            "native_engine_invocations": 0, "original_active_ledger_unchanged": True}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--scope", type=Path)
    parser.add_argument("--writer", type=Path)
    parser.add_argument("--number", type=int)
    parser.add_argument("--sleeper", action="store_true")
    args = parser.parse_args()
    sys.dont_write_bytecode = True
    os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
    os.umask(0o077)
    if args.writer:
        raise SystemExit(writer(args.writer, args.number))
    if args.sleeper:
        sleeper()
        return
    start = time.monotonic()
    result = controls(args.scope.resolve())
    result["seconds"] = time.monotonic() - start
    print(json.dumps(result))


if __name__ == "__main__":
    main()
