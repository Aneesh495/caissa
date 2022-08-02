"""Atomic paired selfplay journal with immutable configuration and restart checks."""

import argparse, concurrent.futures, hashlib, json, os, signal, subprocess, time, fcntl, resource, shutil, uuid, math
from pathlib import Path

SCHEMA = "caissa-selfplay-v1"


def digest(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def atomic_json(path, value):
    path = Path(path)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w") as f:
        json.dump(value, f, separators=(",", ":"))
        f.write("\n")
        f.flush()
        os.fsync(f.fileno())
    tmp.replace(path)
    fd = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def run_pair(engine, root, pair, nodes, seed, timeout, policy="legacy-v1"):
    folder = root / f"{pair//256:06d}"
    folder.mkdir(exist_ok=True)
    path = folder / f"{pair:09d}.json"
    pair_seed = (seed + pair * 6364136223846793005) & ((1 << 64) - 1)
    command = [
        engine,
        "--selfplay-pair",
        str(pair),
        str(pair_seed),
        str(nodes),
        str(16 + (pair % 9) * 2),
    ]
    if policy == "searched-v2":
        command.append(policy)
    start = time.monotonic()
    result = subprocess.run(command, capture_output=True, text=True, timeout=timeout)
    if result.returncode:
        raise RuntimeError(f"pair {pair} failed: {result.stderr[-1000:]}")
    games = [json.loads(l) for l in result.stdout.splitlines()]
    if (
        len(games) != 2
        or [g["reverse"] for g in games] != [0, 1]
        or any(g["pair"] != pair for g in games)
    ):
        raise ValueError("paired output identity")
    for g in games:
        if g.get("search_policy", "legacy-v1") != policy:
            raise ValueError("native selfplay policy differs from declared campaign")
        if g["complete"] != (g["result"] != "*"):
            raise ValueError("completion/result disagreement")
        if not g["moves"]:
            raise ValueError("empty game transcript")
        if not g["positions"] and not g["complete"]:
            raise ValueError("unfinished game has no search samples")
    item = {
        "schema": SCHEMA,
        "pair": pair,
        "command": command,
        "exit": result.returncode,
        "seconds": time.monotonic() - start,
        "games": games,
    }
    atomic_json(path, item)
    return (
        pair,
        sum(g["complete"] for g in games),
        sum(len(g["positions"]) for g in games),
        path.stat().st_size,
    )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--engine", default="build/caissa")
    ap.add_argument("--output", type=Path, required=True)
    ap.add_argument("--pairs", type=int, default=100)
    ap.add_argument("--nodes", type=int, default=500)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--seed", type=int, default=271828)
    ap.add_argument("--timeout", type=int, default=120)
    ap.add_argument(
        "--policy", choices=["legacy-v1", "searched-v2"], default="legacy-v1"
    )
    ap.add_argument("--stop-prepared", type=Path)
    ap.add_argument("--max-preparation-lag-pairs", type=int, default=0)
    ap.add_argument("--target-training-inputs", type=int, default=10100000)
    ap.add_argument("--minimum-training-inputs", type=int, default=10000000)
    ap.add_argument("--minimum-completed-games", type=int, default=100000)
    ap.add_argument("--max-child-cpu-seconds", type=float, default=0)
    ap.add_argument("--max-seconds", type=float, default=0)
    ap.add_argument("--max-gib", type=float, default=40)
    ap.add_argument("--min-free-gib", type=float, default=10)
    a = ap.parse_args()
    if a.max_preparation_lag_pairs and (
        a.stop_prepared is None or not 100 <= a.max_preparation_lag_pairs <= 500000
    ):
        ap.error("preparation backpressure requires a progress path and lag100..500000")
    if a.max_preparation_lag_pairs < 0:
        ap.error("preparation lag must be nonnegative")
    if (
        any(
            not math.isfinite(v) or v < 0
            for v in [a.max_seconds, a.max_gib, a.min_free_gib, a.max_child_cpu_seconds]
        )
        or a.max_gib == 0
    ):
        ap.error("finite nonnegative operational budgets required")
    if (
        a.stop_prepared is not None
        and not 0 < a.minimum_training_inputs <= a.target_training_inputs
        or a.minimum_completed_games < 1
    ):
        ap.error("invalid screened data acquisition target")
    if not 1 <= a.workers <= 8 or not 1 <= a.pairs <= 500000:
        ap.error("resource bounds exceeded")
    a.output.mkdir(parents=True, exist_ok=True)
    writer = (a.output / "CORPUS.lock").open("a")
    fcntl.flock(writer.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    engine = str(Path(a.engine).resolve())
    config = {
        "schema": SCHEMA,
        "engine_sha256": digest(engine),
        "seed": a.seed,
        "nodes": a.nodes,
        "requested_pairs": a.pairs,
        "max_plies": 512,
        "opening_policy": "random-16-to-32-plies; near-best-30cp-first-12-v1",
        "outcome_perspective": "white",
        "search_score_perspective": "side-to-move",
    }
    if a.policy == "searched-v2":
        config["search_policy"] = a.policy
        config["opening_policy"] = (
            "random-16-to-32-plies; seeded-root-order-v2; single principal variation"
        )
    cfg = a.output / "CONFIG.json"
    if cfg.exists():
        if json.loads(cfg.read_text()) != config:
            raise ValueError("resume configuration or executable identity changed")
    else:
        atomic_json(cfg, config)
    config_sha = digest(cfg)
    done = set()
    completed = 0
    samples = 0
    output_bytes = 0
    for path in sorted(a.output.glob("*/*.json")):
        output_bytes += path.stat().st_size
        record = json.loads(path.read_text())
        pair = record["pair"]
        if (
            record["schema"] != SCHEMA
            or pair in done
            or not 0 <= pair < a.pairs
            or len(record["games"]) != 2
        ):
            raise ValueError("invalid completed pair journal")
        done.add(pair)
        completed += sum(g["complete"] for g in record["games"])
        samples += sum(len(g["positions"]) for g in record["games"])
    history = []
    if (a.output / "SESSIONS.jsonl").exists():
        history = [
            json.loads(line)
            for line in (a.output / "SESSIONS.jsonl").read_text().splitlines()
        ]
    started = {event["session"] for event in history if event["event"] == "started"}
    finished = {event["session"] for event in history if event["event"] == "finished"}
    if a.max_child_cpu_seconds and started - finished:
        raise ValueError(
            "an earlier session has incomplete CPU accounting; retain it as diagnostic instead of resetting the budget"
        )
    previous_child_cpu = sum(
        event.get("child_cpu_seconds_this_session", 0)
        for event in history
        if event["event"] == "finished"
    )
    origin = min(
        (
            event.get("campaign_wall_origin_unix", event["utc_unix"])
            for event in history
            if event["event"] == "started"
        ),
        default=time.time(),
    )
    start = time.monotonic()
    wall_start = time.time()
    cpu_start = resource.getrusage(resource.RUSAGE_CHILDREN)
    session = uuid.uuid4().hex
    stop_reason = None

    def journal(event):
        with (a.output / "SESSIONS.jsonl").open("a") as log:
            log.write(json.dumps(event, separators=(",", ":")) + "\n")
            log.flush()
            os.fsync(log.fileno())

    journal(
        {
            "event": "started",
            "session": session,
            "utc_unix": wall_start,
            "workers": a.workers,
            "initial_pairs": len(done),
            "max_seconds": a.max_seconds,
            "max_child_cpu_seconds": a.max_child_cpu_seconds,
            "previous_child_cpu_seconds": previous_child_cpu,
            "campaign_wall_origin_unix": origin,
            "stop_prepared": (
                str(a.stop_prepared) if a.stop_prepared is not None else None
            ),
            "target_training_inputs": (
                a.target_training_inputs if a.stop_prepared is not None else None
            ),
            "max_preparation_lag_pairs": a.max_preparation_lag_pairs,
            "resume_preparation_lag_pairs": a.max_preparation_lag_pairs // 2,
            "minimum_training_inputs": (
                a.minimum_training_inputs if a.stop_prepared is not None else None
            ),
            "minimum_completed_games": (
                a.minimum_completed_games if a.stop_prepared is not None else None
            ),
            "max_gib": a.max_gib,
            "min_free_gib": a.min_free_gib,
            "timing_note": "wall seconds and monotonic seconds recorded separately; CPU counts only reaped children in this session",
        }
    )

    def interrupted(signum, frame):
        nonlocal stop_reason
        stop_reason = "signal-" + str(signum)

    signal.signal(signal.SIGTERM, interrupted)
    signal.signal(signal.SIGINT, interrupted)

    def prepared_progress():
        if a.stop_prepared is None or not a.stop_prepared.exists():
            return None
        marker = json.loads(a.stop_prepared.read_text())
        if (
            marker.get("corpus_root") != str(a.output.resolve())
            or marker.get("corpus_config_sha256") != config_sha
        ):
            return None
        if not isinstance(marker.get("source_pairs"), int) or marker[
            "source_pairs"
        ] > len(done):
            return None
        return marker

    def budget():
        if stop_reason:
            return stop_reason
        if a.max_seconds > 0 and time.time() - origin >= a.max_seconds:
            return "wall-time-budget"
        current_cpu = resource.getrusage(resource.RUSAGE_CHILDREN)
        consumed = (
            previous_child_cpu
            + current_cpu.ru_utime
            + current_cpu.ru_stime
            - cpu_start.ru_utime
            - cpu_start.ru_stime
        )
        if a.max_child_cpu_seconds and consumed >= a.max_child_cpu_seconds:
            return "child-cpu-scheduling-budget"
        if output_bytes >= a.max_gib * 1024**3:
            return "output-byte-budget"
        if shutil.disk_usage(a.output).free < a.min_free_gib * 1024**3:
            return "free-space-budget"
        marker = prepared_progress()
        if (
            marker is not None
            and marker["counts"].get("distinct_train_inputs", 0)
            >= a.target_training_inputs
            and marker["counts"]["completed_games"] >= a.minimum_completed_games
            and marker["counts"].get("distinct_validation_inputs", 0) > 0
            and marker["counts"].get("distinct_test_inputs", 0) > 0
        ):
            return "screened-training-target"
        return None

    pending = iter(i for i in range(a.pairs) if i not in done)
    with concurrent.futures.ThreadPoolExecutor(max_workers=a.workers) as pool:
        running = {}
        exhausted = False
        throttled = False
        last_progress = 0.0

        def preparation_ready():
            nonlocal throttled
            if not a.max_preparation_lag_pairs:
                return True
            marker = prepared_progress()
            consumed = marker["source_pairs"] if marker is not None else 0
            backlog = len(done) + len(running) - consumed
            previous = throttled
            if backlog >= a.max_preparation_lag_pairs:
                throttled = True
            elif throttled and backlog <= a.max_preparation_lag_pairs // 2:
                throttled = False
            if previous != throttled:
                journal(
                    {
                        "event": (
                            "preparation-throttled"
                            if throttled
                            else "preparation-resumed"
                        ),
                        "utc_unix": time.time(),
                        "session": session,
                        "completed_pairs": len(done),
                        "in_flight_pairs": len(running),
                        "observed_prepared_pairs": consumed,
                        "backlog_pairs": backlog,
                        "maximum_lag_pairs": a.max_preparation_lag_pairs,
                    }
                )
            return not throttled

        def submit():
            nonlocal stop_reason, exhausted
            stop_reason = budget()
            if stop_reason or exhausted or not preparation_ready():
                return False
            pair = next(pending, None)
            if pair is not None:
                running[
                    pool.submit(
                        run_pair,
                        engine,
                        a.output,
                        pair,
                        a.nodes,
                        a.seed,
                        a.timeout,
                        a.policy,
                    )
                ] = pair
                return True
            exhausted = True
            return False

        while True:
            stop_reason = budget()
            while len(running) < a.workers and submit():
                pass
            if not running and (stop_reason or exhausted):
                break
            finished = set()
            if running:
                finished, _ = concurrent.futures.wait(
                    running, timeout=0.5, return_when=concurrent.futures.FIRST_COMPLETED
                )
            else:
                # Dependency waits still consume the original wall budget.
                # Keep publishing the observed preparation counter below.
                time.sleep(0.2)
            for future in finished:
                running.pop(future)
                pair, complete, positions, size = future.result()
                done.add(pair)
                completed += complete
                samples += positions
                output_bytes += size
            now = time.monotonic()
            if (
                (finished and len(done) % 25 == 0)
                or now - last_progress >= 5
                or (not running and stop_reason)
            ):
                marker = prepared_progress()
                summary = {
                    "status": (
                        "diagnostic"
                        if len(done) < 50000
                        else "data-generated-unverified"
                    ),
                    "pairs": len(done),
                    "completed_games": completed,
                    "positions_before_dedup": samples,
                    "seconds_this_session": time.monotonic() - start,
                    "workers": a.workers,
                    "wall_seconds_this_session": time.time() - wall_start,
                    "output_bytes": output_bytes,
                    "stop_reason": stop_reason,
                    "phase": (
                        "waiting-for-preparation"
                        if throttled and not running
                        else "generating"
                    ),
                    "observed_prepared_pairs": (
                        marker["source_pairs"] if marker is not None else None
                    ),
                    "max_preparation_lag_pairs": a.max_preparation_lag_pairs,
                    "in_flight_pairs": len(running),
                }
                atomic_json(a.output / "PROGRESS.json", summary)
                print(json.dumps(summary), flush=True)
                last_progress = now
    completion_proof = None
    target_complete = False
    if stop_reason == "screened-training-target":
        wait_start = time.time()
        while stop_reason == "screened-training-target":
            marker = prepared_progress()
            if marker is not None and marker["source_pairs"] == len(done):
                completion_proof = marker
                target_complete = (
                    marker["counts"].get("distinct_train_inputs", 0)
                    >= a.minimum_training_inputs
                    and marker["counts"]["completed_games"] >= a.minimum_completed_games
                )
                if not target_complete:
                    stop_reason = "screened-target-invalidated-by-later-data"
                break
            if a.max_seconds and time.time() - origin >= a.max_seconds:
                stop_reason = "wall-time-budget"
                break
            if time.time() - wait_start > 10800:
                stop_reason = "preparation-confirmation-timeout"
                break
            time.sleep(0.2)
    complete = len(done) == a.pairs or target_complete
    cpu_end = resource.getrusage(resource.RUSAGE_CHILDREN)
    final = {
        "status": "completed" if complete else "interrupted",
        "completion_mode": "screened-target" if target_complete else "fixed-pairs",
        "completion_proof": completion_proof,
        "pairs": len(done),
        "completed_games": completed,
        "positions_before_dedup": samples,
        "config": config,
        "seconds_this_session": time.monotonic() - start,
        "wall_seconds_this_session": time.time() - wall_start,
        "child_cpu_seconds_this_session": cpu_end.ru_utime
        + cpu_end.ru_stime
        - cpu_start.ru_utime
        - cpu_start.ru_stime,
        "parent_cpu_seconds": time.process_time(),
        "campaign_child_cpu_seconds": previous_child_cpu
        + cpu_end.ru_utime
        + cpu_end.ru_stime
        - cpu_start.ru_utime
        - cpu_start.ru_stime,
        "campaign_wall_origin_unix": origin,
        "workers": a.workers,
        "output_bytes": output_bytes,
        "stop_reason": stop_reason,
        "max_preparation_lag_pairs": a.max_preparation_lag_pairs,
        "session": session,
    }
    journal({"event": "finished", "utc_unix": time.time(), **final})
    atomic_json(
        a.output / ("SUMMARY.json" if complete else "INTERRUPTED.json"),
        final,
    )
    if not complete:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
