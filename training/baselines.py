"""Freeze original classical scores for residual learning, without test access."""

import argparse
import fcntl
import json
import os
import shutil
import subprocess
from pathlib import Path

import numpy as np

from training.corpus import atomic_json, digest
from training.features import normalized_fen_from_features


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("dataset", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--engine", type=Path, default=Path("build/caissa"))
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    if args.output.resolve().is_relative_to(args.dataset.resolve()):
        raise ValueError("residual scores must use a separate artifact directory")
    manifest = json.loads((args.dataset / "DATASET.json").read_text())
    args.output.mkdir(parents=True, exist_ok=args.resume)
    lock = (args.output / "BASELINE.lock").open("a")
    fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    config = {
        "schema": "caissa-classical-baselines-v1",
        "classical_contract": 1,
        "dataset_sha256": digest(args.dataset / "DATASET.json"),
        "engine_sha256": digest(args.engine),
        "splits": {key: manifest["splits"][key] for key in ["train", "validation"]},
        "test_accessed": False,
        "normalization": "mover-oriented white placement; omitted rule metadata does not affect classical contract 1",
    }
    cfg = args.output / "CONFIG.json"
    if cfg.exists() and json.loads(cfg.read_text()) != config:
        raise ValueError("baseline resume inputs changed")
    atomic_json(cfg, config)
    binary = args.output / "caissa"
    if binary.exists():
        if digest(binary) != config["engine_sha256"]:
            raise ValueError("frozen baseline executable differs")
    else:
        shutil.copy2(args.engine, binary)
    pointer = args.output / "PROGRESS.json"
    progress = (
        json.loads(pointer.read_text())
        if pointer.exists()
        else {"train": 0, "validation": 0}
    )
    process = subprocess.Popen(
        [str(binary.resolve()), "--eval-probe"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        bufsize=1,
    )
    files = {}
    try:
        for split in ["train", "validation"]:
            name = f"{split}-features.npy"
            if digest(args.dataset / name) != manifest["files"][name]:
                raise ValueError("baseline source features changed")
            source = np.load(args.dataset / name, mmap_mode="r", allow_pickle=False)
            path = args.output / f"{split}-baseline.npy"
            partial = args.output / f"{split}-baseline.partial.npy"
            n = len(source)
            if progress[split] == n and path.exists():
                files[path.name] = digest(path)
                continue
            if partial.exists() and not args.resume:
                raise ValueError("partial baseline requires explicit resume")
            output = np.lib.format.open_memmap(
                partial,
                mode="r+" if partial.exists() else "w+",
                dtype=np.int16,
                shape=(n,),
            )
            for offset in range(progress[split], n, 64):
                end = min(offset + 64, n)
                fens = [normalized_fen_from_features(row) for row in source[offset:end]]
                process.stdin.write("\n".join(fens) + "\n")
                process.stdin.flush()
                for index in range(offset, end):
                    line = process.stdout.readline(4096)
                    if not line:
                        raise ValueError("native classical baseline process exited")
                    record = json.loads(line)
                    score = record["classical"]
                    if (
                        record["contract"] != 1
                        or not isinstance(score, int)
                        or not -29871 <= score <= 29871
                    ):
                        raise ValueError("native classical numerical contract differs")
                    output[index] = score
                if end % 8192 == 0 or end == n:
                    output.flush()
                    with partial.open("rb") as stream:
                        os.fsync(stream.fileno())
                    progress[split] = end
                    atomic_json(pointer, progress)
                    print(
                        json.dumps({"split": split, "completed": end, "positions": n}),
                        flush=True,
                    )
            output.flush()
            del output
            partial.replace(path)
            files[path.name] = digest(path)
        atomic_json(
            args.output / "BASELINES.json",
            {
                "schema": "caissa-classical-baselines-v1",
                "config": config,
                "files": files,
                "test_accessed": False,
            },
        )
    finally:
        process.stdin.close()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
    if process.returncode:
        raise ValueError("baseline executable returned failure")
    print(
        json.dumps(
            {
                "status": "completed",
                "splits": config["splits"],
                "test_accessed": False,
                "manifest_sha256": digest(args.output / "BASELINES.json"),
            }
        )
    )


if __name__ == "__main__":
    main()
