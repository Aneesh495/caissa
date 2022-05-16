"""SIGKILL during replay must preserve exactly one committed source batch."""

import argparse, json, os, signal, subprocess, sys, time
from pathlib import Path
from training.corpus import digest


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--corpus", type=Path, required=True)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    folder = args.output / "prepared"
    command = [sys.executable, "-m", "training.prepare", str(args.corpus), str(folder)]
    with (args.output / "interrupted.log").open("w") as log:
        process = subprocess.Popen(
            command, stdout=log, stderr=subprocess.STDOUT, start_new_session=True
        )
        deadline = time.monotonic() + 120
        while True:
            progress = folder / "PREPARE_PROGRESS.json"
            if (
                progress.exists()
                and json.loads(progress.read_text())["source_pairs"] >= 100
            ):
                break
            if process.poll() is not None:
                raise ValueError("preparation exited before interruption")
            if time.monotonic() > deadline:
                os.killpg(process.pid, signal.SIGKILL)
                raise TimeoutError("no preparation transaction committed")
            time.sleep(0.005)
        state = json.loads(progress.read_text())
        os.killpg(process.pid, signal.SIGKILL)
        process.wait(timeout=5)
    with (args.output / "resumed.log").open("w") as log:
        subprocess.run(
            command + ["--resume"],
            stdout=log,
            stderr=subprocess.STDOUT,
            check=True,
            timeout=180,
        )
    reference = json.loads((args.baseline / "DATASET.json").read_text())
    resumed = json.loads((folder / "DATASET.json").read_text())
    for key in [
        "files",
        "splits",
        "counts",
        "histograms",
        "corpus_content_sha256",
        "source_pairs_sha256",
        "heldout_inputs",
    ]:
        if reference[key] != resumed[key]:
            raise ValueError("resumed preparation changed " + key)
    for name in reference["splits"]:
        if digest(args.baseline / f"{name}-identities.jsonl") != digest(
            folder / f"{name}-identities.jsonl"
        ):
            raise ValueError("resumed identity lineage differs")
    result = {
        "status": "passed",
        "signal": "SIGKILL",
        "committed_sources_before": state["source_pairs"],
        "source_pairs_after": len(
            json.loads((folder / "SOURCE_PAIRS.json").read_text())
        ),
        "arrays_and_identities_bit_identical": True,
        "all_counts_and_histograms_identical": True,
    }
    (args.output / "RECOVERY.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result))


if __name__ == "__main__":
    main()
