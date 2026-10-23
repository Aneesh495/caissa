"""Real producer pause/restart, unchanged pair bytes and delayed consumer."""

import argparse
import hashlib
import json
import signal
import subprocess
import sys
import time
from pathlib import Path


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def wait_for(predicate, processes, seconds):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        result = predicate()
        if result:
            return result
        if any(process.poll() is not None for process in processes):
            raise RuntimeError(
                "owned producer/consumer exited before expected progress"
            )
        time.sleep(0.1)
    raise TimeoutError("backpressure control progress deadline")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--engine", required=True)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    corpus = args.output / "corpus"
    prepared = args.output / "prepared"
    command = [
        sys.executable,
        "-m",
        "training.corpus",
        "--engine",
        args.engine,
        "--output",
        str(corpus),
        "--pairs",
        "320",
        "--nodes",
        "2000",
        "--workers",
        "4",
        "--policy",
        "searched-v2",
        "--max-seconds",
        "240",
        "--max-child-cpu-seconds",
        "2000",
        "--max-gib",
        "1",
        "--min-free-gib",
        "1",
        "--stop-prepared",
        str(prepared / "PREPARE_PROGRESS.json"),
        "--target-training-inputs",
        "100000000",
        "--max-preparation-lag-pairs",
        "128",
    ]
    processes = []
    logs = []
    start = time.monotonic()

    def launch(name, argv):
        stream = (args.output / (name + ".log")).open("xb")
        logs.append(stream)
        process = subprocess.Popen(argv, stdout=stream, stderr=subprocess.STDOUT)
        processes.append(process)
        return process

    try:
        first = launch("producer-first", command)

        def paused():
            path = corpus / "PROGRESS.json"
            if not path.exists():
                return None
            value = json.loads(path.read_text())
            return (
                value
                if value.get("phase") == "waiting-for-preparation"
                and value["in_flight_pairs"] == 0
                else None
            )

        observed = wait_for(paused, [first], 100)
        if observed["pairs"] != 128:
            raise ValueError(
                "producer admission exceeded the frozen preparation backlog"
            )
        before = {
            str(p.relative_to(corpus)): digest(p)
            for p in sorted(corpus.glob("*/*.json"))
        }
        if len(before) != 128:
            raise ValueError("paused producer omitted completed journals")
        first.send_signal(signal.SIGTERM)
        if first.wait(timeout=15) != 2:
            raise ValueError(
                "graceful producer interruption was not retained as incomplete"
            )
        interrupted = json.loads((corpus / "INTERRUPTED.json").read_text())
        if interrupted["stop_reason"] != "signal-15" or interrupted["pairs"] != 128:
            raise ValueError("paused interruption changed completed work")
        second = launch("producer-resumed", command)
        wait_for(paused, [second], 30)
        consumer = launch(
            "preparation",
            [
                sys.executable,
                "-m",
                "training.prepare",
                str(corpus),
                str(prepared),
                "--follow",
            ],
        )
        while second.poll() is None or consumer.poll() is None:
            if time.monotonic() - start > 260:
                raise TimeoutError("cumulative backpressure/recovery control ceiling")
            if second.poll() not in [None, 0] or consumer.poll() not in [None, 0]:
                raise RuntimeError("producer or delayed preparation failed")
            time.sleep(0.2)
        if any(digest(corpus / path) != identity for path, identity in before.items()):
            raise ValueError("resumed producer rewrote an existing completed pair")
        sessions = [
            json.loads(line)
            for line in (corpus / "SESSIONS.jsonl").read_text().splitlines()
        ]
        starts = [row for row in sessions if row["event"] == "started"]
        finishes = [row for row in sessions if row["event"] == "finished"]
        if len(starts) != 2 or len(finishes) != 2:
            raise ValueError("missing cumulative session accounting")
        if (
            starts[0]["campaign_wall_origin_unix"]
            != starts[1]["campaign_wall_origin_unix"]
            or starts[1]["previous_child_cpu_seconds"]
            != finishes[0]["child_cpu_seconds_this_session"]
        ):
            raise ValueError("backpressure recovery reset a cumulative resource budget")
        final = json.loads((corpus / "SUMMARY.json").read_text())
        if (
            final["pairs"] != 320
            or final["status"] != "completed"
            or final["campaign_wall_origin_unix"]
            != starts[0]["campaign_wall_origin_unix"]
        ):
            raise ValueError(
                "resumed producer did not finish its unchanged fixed request"
            )
        if not any(row["event"] == "preparation-resumed" for row in sessions):
            raise ValueError("delayed consumer never released producer backpressure")
        verify = subprocess.run(
            [sys.executable, "-m", "verification.dataset", str(prepared), str(corpus)],
            capture_output=True,
            text=True,
            timeout=90,
        )
        (args.output / "independent.log").write_text(verify.stdout + verify.stderr)
        if verify.returncode:
            raise ValueError(
                "independent data replay rejected recovered backpressure corpus"
            )
        result = {
            "status": "passed",
            "profile": "diagnostic real backpressure and recovery",
            "paused_completed_pairs": 128,
            "completed_pairs": 320,
            "unchanged_completed_pair_hashes": len(before),
            "cumulative_wall_origin_preserved": True,
            "prior_measured_child_cpu_preserved": True,
            "independent_dataset_replay_exit": verify.returncode,
            "seconds": time.monotonic() - start,
            "full_acceptance": False,
        }
        (args.output / "CONTROLS.json").write_text(json.dumps(result, indent=2) + "\n")
        print(json.dumps(result))
    finally:
        for process in processes:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
        for stream in logs:
            stream.close()


if __name__ == "__main__":
    main()
