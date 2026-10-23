"""Force-kill actual training and corpus writers, then verify exact recovery."""

import argparse, hashlib, json, os, signal, subprocess, sys, time
from pathlib import Path
from training.corpus import digest


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dataset", default="data/diagnostic-prepared")
    ap.add_argument("--engine", default="runs/frozen-candidate-current/caissa")
    ap.add_argument("--network-version", type=int, choices=[2, 3], default=2)
    ap.add_argument("--baseline-directory")
    ap.add_argument("--output", type=Path, required=True)
    a = ap.parse_args()
    a.output.mkdir(parents=True, exist_ok=False)
    observed = []
    train = [
        sys.executable,
        "-m",
        "training.train",
        a.dataset,
        "OUTPUT",
        "--seed",
        "101",
        "--steps",
        "400",
        "--batch",
        "256",
        "--checkpoint-every",
        "50",
    ]
    if a.network_version == 3:
        train += [
            "--network-version",
            "3",
            "--baseline-directory",
            a.baseline_directory,
        ]

    def command(output):
        return [str(output) if arg == "OUTPUT" else arg for arg in train]

    uninterrupted = a.output / "uninterrupted"
    interrupted = a.output / "interrupted"
    with (a.output / "training-complete.log").open("w") as f:
        subprocess.run(
            command(uninterrupted),
            stdout=f,
            stderr=subprocess.STDOUT,
            check=True,
            timeout=120,
        )
    with (a.output / "training-interrupted.log").open("w") as log:
        process = subprocess.Popen(
            command(interrupted), stdout=log, stderr=subprocess.STDOUT
        )
        deadline = time.monotonic() + 60
        while not (interrupted / "CHECKPOINTS.json").exists():
            if process.poll() is not None:
                raise ValueError("trainer exited before checkpoint interruption")
            if time.monotonic() > deadline:
                process.kill()
                raise TimeoutError("checkpoint not written")
            time.sleep(0.005)
        pointer = json.loads((interrupted / "CHECKPOINTS.json").read_text())
        initial_checkpoint_sha = digest(interrupted / "initial.pt")
        os.kill(process.pid, signal.SIGKILL)
        process.wait(timeout=5)
    with (a.output / "training-resumed.log").open("w") as f:
        subprocess.run(
            command(interrupted) + ["--resume"],
            stdout=f,
            stderr=subprocess.STDOUT,
            check=True,
            timeout=120,
        )
    one = json.loads((uninterrupted / "SUMMARY.json").read_text())
    two = json.loads((interrupted / "SUMMARY.json").read_text())
    if digest(interrupted / "initial.pt") != initial_checkpoint_sha:
        raise ValueError("resumption replaced the original random initialization")
    if (
        one["final_sha256"] != two["final_sha256"]
        or one["best_validation"] != two["best_validation"]
        or one["updates"] != two["updates"]
    ):
        raise ValueError("resumed training differs from uninterrupted run")
    import torch

    best_one = torch.load(
        uninterrupted / "best.pt", map_location="cpu", weights_only=False
    )
    best_two = torch.load(
        interrupted / "best.pt", map_location="cpu", weights_only=False
    )
    if (
        best_one["current_hash"] != best_two["current_hash"]
        or best_one["step"] != best_two["step"]
    ):
        raise ValueError("best checkpoint transaction was lost")
    observed.append(
        {
            "case": "training-forced-SIGKILL",
            "interrupted_after": pointer["last"]["path"],
            "final_parameters_bit_identical": True,
            "best_checkpoint_identical": True,
            "initial_checkpoint_preserved": initial_checkpoint_sha,
            "updates": two["updates"],
        }
    )
    corpus = a.output / "corpus"
    cmd = [
        sys.executable,
        "-m",
        "training.corpus",
        "--engine",
        a.engine,
        "--pairs",
        "30",
        "--nodes",
        "250",
        "--workers",
        "2",
        "--seed",
        "718281",
        "--output",
        str(corpus),
    ]
    with (a.output / "corpus-interrupted.log").open("w") as log:
        process = subprocess.Popen(
            cmd, stdout=log, stderr=subprocess.STDOUT, start_new_session=True
        )
        deadline = time.monotonic() + 30
        while len(list(corpus.glob("*/*.json"))) < 3:
            if process.poll() is not None:
                raise ValueError("corpus exited before interruption")
            if time.monotonic() > deadline:
                os.killpg(process.pid, signal.SIGKILL)
                raise TimeoutError("no corpus checkpoint")
            time.sleep(0.01)
        frozen = {
            str(p.relative_to(corpus)): digest(p) for p in corpus.glob("*/*.json")
        }
        os.killpg(process.pid, signal.SIGKILL)
        process.wait(timeout=5)
    # A torn temporary write must not be mistaken for a completed pair.
    (corpus / "000000" / "000000029.json.tmp").write_text('{"torn":')
    with (a.output / "corpus-resumed.log").open("w") as log:
        subprocess.run(
            cmd, stdout=log, stderr=subprocess.STDOUT, check=True, timeout=120
        )
    for relative, value in frozen.items():
        if digest(corpus / relative) != value:
            raise ValueError("completed corpus pair was changed during resume")
    paths = list(corpus.glob("*/*.json"))
    ids = [json.loads(p.read_text())["pair"] for p in paths]
    if sorted(ids) != list(range(30)):
        raise ValueError("lost or duplicated completed corpus pair")
    observed.append(
        {
            "case": "corpus-forced-SIGKILL",
            "completed_before": len(frozen),
            "completed_after": len(paths),
            "preserved_completed_bytes": True,
            "ignored_torn_file": True,
        }
    )
    (a.output / "RECOVERY.json").write_text(json.dumps(observed, indent=2) + "\n")
    print(json.dumps(observed))


if __name__ == "__main__":
    main()
