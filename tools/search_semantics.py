"""Bounded observations of the original search and table diagnostic API."""

import argparse
import hashlib
import json
import random
import subprocess
import time
from pathlib import Path

from tools.campaign_process import atomic
from tools.heuristic_study import avoid_decisive_matches
from verification.tactical_generation import Probe


def program(rule):
    rng = random.Random(rule["table_seed"])
    for index in range(rule["table_samples"]):
        key = rng.getrandbits(64)
        other = key ^ (1 << 48)
        source, target = index % 63, (index + 17) % 63
        score = rule["table_scores"][index % len(rule["table_scores"])]
        depth, bound, ply = (
            [0, 8, 16, 64][index % 4],
            1 + index % 3,
            [0, 1, 7, 127][index % 4],
        )
        identity = "table-" + str(index)
        yield identity, "table", "clear"
        yield identity, "table", "new"
        yield identity, "table", f"store {key:016x} {source} {target} {score} {index-48} {depth} {bound} {ply} end"
        for query in [0, 3, 17, 127]:
            yield identity, "table", f"probe {key:016x} {query}"
        yield identity, "table", f"probe {other:016x} 0"
        yield identity, "table", f"hint {other:016x} {source} {target} 8"
        yield identity, "table", f"probe {other:016x} 0"
        yield identity, "table", f"store {key:016x} {target} {source} 7 -1 0 2 0 end"
        yield identity, "table", f"probe {key:016x} 7"
        yield identity, "table", "clear"
        yield identity, "table", f"probe {key:016x} 0"
    for case in rule["cases"]:
        for depth in case["depths"]:
            for flags in rule["exact_flags"]:
                for seed in rule["exact_seeds"]:
                    name = f"exact/{case['id']}/{depth}/{flags}/{seed}"
                    yield name, "clear", "clear"
                    yield name, "exact", request(case, depth, flags, seed, rule)
    witness = next(
        case for case in rule["cases"] if case["id"] == "lmr-window-regression"
    )
    for flags in rule["lmr_witness_flags"]:
        name = "regression/lmr/" + str(flags)
        yield name, "clear", "clear"
        yield name, "regression", request(witness, 5, flags, 0, rule)
    for identity in rule["ablation_cases"]:
        case = next(case for case in rule["cases"] if case["id"] == identity)
        for off in [0, *rule["ablation_switch_bits"]]:
            name = f"ablation/{identity}/{off}"
            flags = rule["ablation_reference_flags"] ^ off
            yield name, "clear", "clear"
            yield name, "ablation", request(
                case, rule["ablation_depth"], flags, 0, rule
            )


def request(case, depth, flags, seed, rule):
    return f"search {depth} {flags} {seed} {rule['maximum_native_nodes']} {int(case['chess960'])}|{case['fen']}|{' '.join(case['moves'])}"


def main():
    parser = argparse.ArgumentParser()
    for name in ["engine", "profile", "output"]:
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--expected-profile-sha256", required=True)
    args = parser.parse_args()
    avoid_decisive_matches()
    profile = args.profile.read_bytes()
    if hashlib.sha256(profile).hexdigest() != args.expected_profile_sha256:
        raise ValueError("search profile external identity differs")
    rule = json.loads(profile)
    args.output.mkdir(parents=True, exist_ok=False)
    (args.output / "profile.json").write_bytes(profile)
    active, started = time.monotonic(), time.time()
    deadline = started + rule["maximum_producer_seconds"]
    config = {
        "schema": "caissa-search-semantics-sample-v1",
        "source_commit": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], text=True, timeout=5
        ).strip(),
        "engine_sha256": hashlib.sha256(args.engine.read_bytes()).hexdigest(),
        "profile_sha256": args.expected_profile_sha256,
        "maximum_seconds": rule["maximum_producer_seconds"],
        "deadline_unix": deadline,
        "full_acceptance": False,
    }
    atomic(args.output / "CONFIG.json", config)
    native, count, last = None, 0, None
    digest = hashlib.sha256()
    try:
        native = Probe(args.engine, "--search-probe", deadline)
        with (args.output / "observations.jsonl").open("xb") as stream:
            for index, (name, kind, command) in enumerate(program(rule)):
                if (
                    time.time() >= deadline
                    or time.monotonic() - active >= rule["maximum_producer_seconds"]
                ):
                    raise TimeoutError("search producer deadline exhausted")
                last = {"index": index, "name": name, "kind": kind, "command": command}
                actual = native.request(command)
                if "error" in actual:
                    raise ValueError("native search request rejected: " + str(actual))
                row = {
                    **last,
                    "actual": actual,
                    "response_sha256": hashlib.sha256(native.last_response).hexdigest(),
                }
                raw = (
                    json.dumps(row, separators=(",", ":"), allow_nan=False) + "\n"
                ).encode()
                stream.write(raw)
                digest.update(raw)
                count += 1
                if (
                    count > rule["maximum_commands"]
                    or stream.tell() > rule["maximum_observation_bytes"]
                ):
                    raise ValueError("search producer raw ceiling exhausted")
                if count % 64 == 0:
                    atomic(
                        args.output / "PROGRESS.json", {**last, "observations": count}
                    )
        native.close()
        if native.process.returncode != 0 or native.stderr or native.buffer:
            raise ValueError("search producer native exit or transport differs")
        atomic(
            args.output / "SUMMARY.json",
            {
                **config,
                "status": "observed",
                "observations": count,
                "observations_sha256": digest.hexdigest(),
                "native_exit": native.process.returncode,
                "elapsed_seconds": time.monotonic() - active,
            },
        )
    except BaseException as error:
        atomic(
            args.output / "FAILED.json",
            {"reason": str(error), "observations": count, "last": last},
        )
        raise
    finally:
        if native is not None and native.process.poll() is None:
            native.close()
        if native is not None:
            (args.output / "stderr.log").write_bytes(native.stderr)


if __name__ == "__main__":
    main()
