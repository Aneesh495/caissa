"""End a diagnostic corpus on real screened counts, then independently replay it."""

import argparse, json, os, subprocess, sys, time
from pathlib import Path
from verification.dataset import verify_dataset


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--engine", default="build/caissa")
    parser.add_argument("--nodes", type=int, default=500)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--interrupt", action="store_true")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    corpus = args.output / "corpus"
    dataset = args.output / "prepared"
    producer = [
        sys.executable,
        "-m",
        "training.corpus",
        "--engine",
        args.engine,
        "--pairs",
        "5000",
        "--nodes",
        str(args.nodes),
        "--workers",
        "2",
        "--policy",
        "searched-v2",
        "--max-seconds",
        "300",
        "--stop-prepared",
        str(dataset / "PREPARE_PROGRESS.json"),
        "--target-training-inputs",
        "5000",
        "--minimum-training-inputs",
        "4000",
        "--minimum-completed-games",
        "1",
        "--output",
        str(corpus),
    ]
    preparation = [
        sys.executable,
        "-m",
        "training.prepare",
        str(corpus),
        str(dataset),
        "--follow",
    ]
    processes = []
    preserved = {}
    with (
        (args.output / "producer.log").open("w") as one,
        (args.output / "preparation.log").open("w") as two,
    ):
        try:
            source = subprocess.Popen(producer, stdout=one, stderr=subprocess.STDOUT)
            processes.append(source)
            deadline = time.monotonic() + 30
            while not (corpus / "CONFIG.json").exists():
                if source.poll() is not None:
                    raise ValueError("producer exited before initialization")
                if time.monotonic() > deadline:
                    raise TimeoutError("producer configuration missing")
                time.sleep(0.02)
            prepare = subprocess.Popen(
                preparation, stdout=two, stderr=subprocess.STDOUT
            )
            processes.append(prepare)
            if args.interrupt:
                deadline = time.monotonic() + 60
                while (
                    len(list(corpus.glob("*/*.json"))) < 8
                    or not (dataset / "PREPARE_PROGRESS.json").exists()
                ):
                    if source.poll() is not None or prepare.poll() is not None:
                        raise ValueError("acquisition exited before interruption")
                    if time.monotonic() > deadline:
                        raise TimeoutError(
                            "no acquisition checkpoint before interruption"
                        )
                    time.sleep(0.02)
                # Preparation rolls back its uncommitted tail. The producer drains
                # bounded children and records CPU before its replacement starts.
                prepare.terminate()
                prepare.wait(timeout=10)
                source.terminate()
                if source.wait(timeout=120) != 2:
                    raise ValueError(
                        "graceful acquisition interruption was not recorded"
                    )
                import hashlib

                preserved = {
                    str(path.relative_to(corpus)): hashlib.sha256(
                        path.read_bytes()
                    ).hexdigest()
                    for path in corpus.glob("*/*.json")
                }
                source = subprocess.Popen(
                    producer, stdout=one, stderr=subprocess.STDOUT
                )
                processes.append(source)
                deadline = time.monotonic() + 30
                while len((corpus / "SESSIONS.jsonl").read_text().splitlines()) < 3:
                    if source.poll() is not None or time.monotonic() > deadline:
                        raise ValueError("resumed producer did not start")
                    time.sleep(0.02)
                prepare = subprocess.Popen(
                    preparation + ["--resume"], stdout=two, stderr=subprocess.STDOUT
                )
                processes.append(prepare)
            if source.wait(timeout=300) != 0:
                raise ValueError("target producer did not complete")
            if prepare.wait(timeout=180) != 0:
                raise ValueError("target preparation did not export")
        finally:
            for process in processes:
                if process.poll() is None:
                    process.terminate()
            for process in processes:
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
    summary = json.loads((corpus / "SUMMARY.json").read_text())
    manifest = json.loads((dataset / "DATASET.json").read_text())
    assert summary["completion_mode"] == "screened-target" and summary["pairs"] < 5000
    assert manifest["splits"]["train"] >= 4000
    assert (
        summary["completion_proof"]["counts"]["distinct_train_inputs"]
        == manifest["splits"]["train"]
    )
    assert (
        len(json.loads((dataset / "SOURCE_PAIRS.json").read_text())) == summary["pairs"]
    )
    if args.interrupt:
        import hashlib

        for relative, expected in preserved.items():
            assert (
                hashlib.sha256((corpus / relative).read_bytes()).hexdigest() == expected
            )
        sessions = [
            json.loads(line)
            for line in (corpus / "SESSIONS.jsonl").read_text().splitlines()
        ]
        finished = [event for event in sessions if event["event"] == "finished"]
        assert len(finished) == 2
        assert (
            sessions[2]["previous_child_cpu_seconds"]
            == finished[0]["child_cpu_seconds_this_session"]
        )
        assert (
            sessions[2]["campaign_wall_origin_unix"]
            == sessions[0]["campaign_wall_origin_unix"]
        )
        assert summary["campaign_child_cpu_seconds"] == sum(
            event["child_cpu_seconds_this_session"] for event in finished
        )
    verified = verify_dataset(
        dataset,
        corpus,
        Path("config/studies.json"),
        Path("config/strength-openings.json"),
    )
    result = {
        "status": "passed",
        "profile": "diagnostic",
        "pairs": summary["pairs"],
        "maximum_pairs": 5000,
        "actual_train_inputs": manifest["splits"]["train"],
        "source_and_preparation_confirm_same_boundary": True,
        "independent_replay": verified["status"],
        "resumed_completed_pair_bytes_preserved": len(preserved),
        "cumulative_budget_recovery": args.interrupt,
        "full_acceptance": False,
    }
    (args.output / "TARGET.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result))


if __name__ == "__main__":
    main()
