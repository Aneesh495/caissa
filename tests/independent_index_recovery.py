"""SIGKILL an independent replay and resume only its externally pinned state."""

import argparse
import json
import os
import signal
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

from verification.dataset_index import ReplayIndex, snapshot


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--deadline-unix", type=float)
    parser.add_argument("--maximum-seconds", type=int, default=120)
    parser.add_argument(
        "--dataset", type=Path, default=Path("data/searched-2000nodes-prepared")
    )
    parser.add_argument(
        "--corpus", type=Path, default=Path("data/searched-2000nodes-200pairs")
    )
    args = parser.parse_args()
    if not 1 <= args.maximum_seconds <= 600:
        parser.error("finite recovery-control budget required")
    args.deadline_unix = min(
        args.deadline_unix or float("inf"), time.time() + args.maximum_seconds
    )
    args.output.mkdir(parents=True, exist_ok=False)
    scratch = args.output / "index"
    scratch.mkdir()
    progress = args.output / "PROGRESS.json"
    base = [
        sys.executable,
        "-m",
        "verification.dataset",
        str(args.dataset),
        str(args.corpus),
        "--max-seconds",
        "120",
        "--retain-index",
        "--checkpoint-pairs",
        "1",
    ]
    command = [*base, "--scratch", str(scratch), "--progress", str(progress)]
    child = subprocess.Popen(
        command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True
    )
    try:
        until = min(args.deadline_unix, time.time() + 30)
        observed = None
        while time.time() < until:
            if progress.exists():
                observed = json.loads(progress.read_text())
                if (
                    observed.get("phase") == "committed-original-games"
                    and observed.get("source_pairs", 0) > 0
                ):
                    break
            if child.poll() is not None:
                raise AssertionError(
                    "diagnostic replay finished before forced interruption"
                )
            time.sleep(0.002)
        else:
            raise TimeoutError(
                "independent replay made no committed progress before test deadline"
            )
        os.killpg(child.pid, signal.SIGKILL)
        child.wait(timeout=3)
        stdout, stderr = child.communicate(timeout=3)
        (args.output / "INTERRUPTED.stdout").write_bytes(stdout)
        (args.output / "INTERRUPTED.stderr").write_bytes(stderr)
        assert child.returncode == -signal.SIGKILL
    finally:
        if child.poll() is None:
            os.killpg(child.pid, signal.SIGKILL)
            child.wait(timeout=3)
        for stream in [child.stdout, child.stderr]:
            stream.close()
    index = Path(observed["index"])
    connection = sqlite3.connect(
        (index / "replayed.sqlite3").resolve().as_uri() + "?mode=ro",
        uri=True,
        timeout=1,
    )
    state = json.loads(
        connection.execute(
            "SELECT state FROM replay_checkpoint WHERE singleton=1"
        ).fetchone()[0]
    )
    assert connection.execute("PRAGMA quick_check(1)").fetchone()[0] == "ok"
    connection.close()
    source_count = len(json.loads((args.dataset / "SOURCE_PAIRS.json").read_text()))
    assert (
        0 < state["cursor"] < source_count
        and state["complete_games"] + state["unfinished_games"] == 2 * state["cursor"]
    )
    pinned = snapshot(index)
    resume = [
        *base,
        "--resume-index",
        str(index),
        "--expected-index-state-sha256",
        pinned,
    ]
    result = subprocess.run(
        resume,
        capture_output=True,
        text=True,
        timeout=max(1, min(150, args.deadline_unix - time.time())),
    )
    (args.output / "RESUME.stdout").write_text(result.stdout)
    (args.output / "RESUME.stderr").write_text(result.stderr)
    assert result.returncode == 0, (result.stdout, result.stderr)
    resumed = json.loads(result.stdout)
    # A new pin is necessary after a successful replay checkpoint changes bytes.
    completed_pin = snapshot(index)
    altered = list(resume)
    altered[altered.index("--expected-index-state-sha256") + 1] = "0" * 64
    refused = subprocess.run(altered, capture_output=True, text=True, timeout=30)
    assert refused.returncode == 1 and "externally pinned" in refused.stdout
    (args.output / "WRONG_PIN_REJECTION.stdout").write_text(refused.stdout)
    unpinned = resume[: resume.index("--expected-index-state-sha256")]
    refused_unpinned = subprocess.run(
        unpinned, capture_output=True, text=True, timeout=30
    )
    assert (
        refused_unpinned.returncode == 1
        and "externally pinned" in refused_unpinned.stdout
    )
    (args.output / "UNPINNED_REJECTION.stdout").write_text(refused_unpinned.stdout)
    partial = args.output / "uncommitted"
    ready = args.output / "UNCOMMITTED_READY.json"
    code = """import json,sys,time
from pathlib import Path
from verification.dataset_index import ReplayIndex
root=Path(sys.argv[1]);root.mkdir()
with ReplayIndex(root,True,{"scope":"synthetic-rollback"}) as index:
    connection=index.connection
    connection.execute("PRAGMA cache_size=8")
    before=(index.directory/"replayed.sqlite3-wal").stat().st_size
    for i in range(10000):
        connection.execute("INSERT INTO expected VALUES(?,?,?,?,?,?,?,?,?)",(i.to_bytes(32,"little"),0,"4k3/8/8/8/8/8/8/4K3 w - - 0 1",.5,1.,.5,1,"synthetic:0","synthetic"))
    state=dict(index.state);state.update(cursor=1,complete_games=2,raw_samples=10000,searched_samples=10000,prefix_sha256="1"*64)
    connection.execute("UPDATE replay_checkpoint SET state=?",(json.dumps(state),))
    Path(sys.argv[2]).write_text(json.dumps({"index":str(index.directory),"transaction":connection.in_transaction,"wal_before":before,"wal_after":(index.directory/"replayed.sqlite3-wal").stat().st_size}))
    time.sleep(30)
"""
    dirty = subprocess.Popen(
        [sys.executable, "-c", code, str(partial), str(ready)], start_new_session=True
    )
    try:
        until = min(args.deadline_unix, time.time() + 15)
        while not ready.exists():
            if dirty.poll() is not None:
                raise AssertionError("synthetic transaction exited before kill")
            if time.time() > until:
                raise TimeoutError("synthetic transaction preparation deadline")
            time.sleep(0.002)
        evidence = json.loads(ready.read_text())
        assert (
            evidence["transaction"] is True
            and evidence["wal_after"] > evidence["wal_before"]
        )
        os.killpg(dirty.pid, signal.SIGKILL)
        dirty.wait(timeout=3)
    finally:
        if dirty.poll() is None:
            os.killpg(dirty.pid, signal.SIGKILL)
            dirty.wait(timeout=3)
    directory = Path(evidence["index"])
    with ReplayIndex(
        None, True, {"scope": "synthetic-rollback"}, directory, snapshot(directory)
    ) as index:
        assert (
            index.state["cursor"] == 0
            and index.connection.execute("SELECT count(*) FROM expected").fetchone()[0]
            == 0
        )
    legacy = args.output / "legacy-index"
    legacy.mkdir()
    connection = sqlite3.connect(legacy / "replayed.sqlite3")
    connection.execute("PRAGMA journal_mode=OFF")
    connection.execute("CREATE TABLE expected (id INTEGER)")
    connection.close()
    try:
        ReplayIndex(
            None, True, {"scope": "synthetic-rollback"}, legacy, snapshot(legacy)
        )
    except ValueError as error:
        assert "atomic replay checkpoint" in str(error)
    else:
        raise AssertionError("unversioned journal-OFF scratch index was trusted")
    report = {
        "status": "passed",
        "actual_interruption_exit": child.returncode,
        "committed_pair_cursor": state["cursor"],
        "stopped_index_sha256": pinned,
        "completed_index_sha256": completed_pin,
        "independent_result": resumed,
        "wrong_pin_exit": refused.returncode,
        "unpinned_exit": refused_unpinned.returncode,
        "uncommitted_pages_and_cursor_rolled_back": True,
        "legacy_unsafe_index_refused": True,
        "full_acceptance": False,
    }
    (args.output / "SUMMARY.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report))


if __name__ == "__main__":
    main()
