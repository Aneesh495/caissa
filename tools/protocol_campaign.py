"""Bounded UCI adversary with independently replayable transport timestamps."""

import argparse
import hashlib
import json
import queue
import random
import statistics
import subprocess
import threading
import time
from pathlib import Path

import chess

from tools.campaign_process import atomic


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--engine", type=Path, default=Path("build/caissa"))
    parser.add_argument("--sequences", type=int, default=10000)
    parser.add_argument("--max-seconds", type=float, default=900)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not 1 <= args.sequences <= 100000 or not 1 <= args.max_seconds <= 3600:
        parser.error("workload or duration outside bounds")
    args.output.mkdir(parents=True, exist_ok=False)
    identity = hashlib.sha256(args.engine.read_bytes()).hexdigest()
    config = {
        "schema": "caissa-protocol-audit-v2",
        "requested": args.sequences,
        "engine_sha256": identity,
        "seed": 32452843,
        "maximum_seconds": args.max_seconds,
        "maximum_transcript_bytes": 512 * 1024 * 1024,
        "timestamp_boundary": "send before pipe write; receive after bounded reader queue",
        "stop_p99_limit_ms_exclusive": 50,
        "ponder_sequences": 100,
    }
    atomic(args.output / "CONFIG.json", config)
    rng = random.Random(config["seed"])
    lines = queue.Queue(maxsize=10000)
    started = time.monotonic()
    wall_started = time.time()
    latencies = []
    failure = None
    reader_failure = []
    process = None
    ponder_completed = 0
    byte_count = 0
    with (
        (args.output / "transcript.jsonl").open("x") as log,
        (args.output / "stderr.log").open("x") as stderr,
    ):

        def record(direction, text):
            nonlocal byte_count
            stamp = time.monotonic_ns()
            encoded = (
                json.dumps({direction: text, "ns": stamp}, separators=(",", ":")) + "\n"
            )
            byte_count += len(encoded.encode())
            if byte_count > config["maximum_transcript_bytes"]:
                raise ValueError("protocol transcript byte ceiling")
            log.write(encoded)
            return stamp

        def remaining():
            return min(
                args.max_seconds - (time.monotonic() - started),
                args.max_seconds - (time.time() - wall_started),
            )

        def send(text):
            if remaining() <= 0:
                raise TimeoutError("cumulative protocol audit deadline")
            stamp = record("send", text)
            process.stdin.write(text + "\n")
            process.stdin.flush()
            return stamp

        def until(prefix, timeout=5):
            deadline = time.monotonic() + min(timeout, remaining())
            captured = []
            while True:
                if remaining() <= 0 or time.monotonic() >= deadline:
                    raise TimeoutError("response deadline: " + prefix)
                line = lines.get(timeout=max(0.001, deadline - time.monotonic()))
                if line is None:
                    raise RuntimeError("unexpected engine EOF: " + str(reader_failure))
                stamp = record("receive", line)
                captured.append(line)
                if len(captured) > 5000:
                    raise RuntimeError("engine response flood")
                if line.startswith(prefix):
                    return captured, stamp

        def reader():
            try:
                while True:
                    line = process.stdout.readline(16385)
                    if not line:
                        break
                    if len(line) > 16384:
                        raise RuntimeError("engine output line ceiling")
                    lines.put(line.rstrip("\n"), timeout=1)
            except BaseException as error:
                reader_failure.append(repr(error))
            finally:
                try:
                    lines.put(None, timeout=0.1)
                except queue.Full:
                    pass

        try:
            process = subprocess.Popen(
                [str(args.engine.resolve())],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=stderr,
                text=True,
                bufsize=1,
            )
            thread = threading.Thread(target=reader, daemon=True)
            thread.start()
            send("uci")
            until("uciok")
            send("setoption name Hash value 1")
            send("isready")
            until("readyok")
            board = chess.Board()
            for index in range(args.sequences):
                if index % 71 == 0:
                    board = chess.Board()
                if index % 127 == 0:
                    send("setoption name Hash value 2")
                    send("setoption name Hash value 1")
                if index % 113 == 0:
                    send(
                        "setoption name Threads value " + str(rng.choice([1, 2, 4, 8]))
                    )
                if index % 23 == 0:
                    for bad in [
                        "setoption name Absent value true",
                        "go nodes -1",
                        "position fen garbage",
                        "setoption name Threads value 99",
                        "go movetime 999999999999999999999999999",
                        "position startpos moves a1a8",
                    ]:
                        send(bad)
                send("position fen " + board.fen(en_passant="fen"))
                send("isready")
                until("readyok")
                send(
                    rng.choice(
                        ["go infinite", "go nodes 200", "go movetime 50", "go depth 5"]
                    )
                )
                if index % 3 == 0:
                    time.sleep(0.0005)
                stop = send("stop")
                responses, received = until("bestmove")
                latencies.append((received - stop) / 1e6)
                for line in responses:
                    if line.startswith("info ") and " pv " in line:
                        replay = board.copy()
                        for word in line.split(" pv ", 1)[1].split():
                            move = chess.Move.from_uci(word)
                            if move not in replay.legal_moves:
                                raise RuntimeError(
                                    "illegal principal variation: " + line
                                )
                            replay.push(move)
                best = responses[-1].split()[1]
                if board.is_game_over(claim_draw=False):
                    if (
                        best != "0000"
                        and chess.Move.from_uci(best) not in board.legal_moves
                    ):
                        raise RuntimeError("terminal bestmove illegal")
                    board = chess.Board()
                else:
                    if (
                        best == "0000"
                        or chess.Move.from_uci(best) not in board.legal_moves
                    ):
                        raise RuntimeError(
                            "bestmove illegal in playable position: " + best
                        )
                    board.push(rng.choice(list(board.legal_moves)))
                if (index + 1) % 100 == 0:
                    log.flush()
                    atomic(
                        args.output / "PROGRESS.json",
                        {
                            "completed": len(latencies),
                            "requested": args.sequences,
                            "seconds": time.monotonic() - started,
                        },
                    )
            send("position startpos")
            for _ in range(100):
                send("go ponder depth 1")
                send("ponderhit")
                until("bestmove", timeout=1)
                ponder_completed += 1
            send("X" * 9000)
            send("isready")
            until("readyok")
            send("quit")
            if process.wait(timeout=5) != 0:
                raise RuntimeError("engine exit was nonzero")
            thread.join(timeout=2)
            if thread.is_alive() or reader_failure:
                raise RuntimeError(
                    "engine reader did not finish cleanly: " + str(reader_failure)
                )
            if hashlib.sha256(args.engine.read_bytes()).hexdigest() != identity:
                raise ValueError("engine bytes changed during audit")
        except BaseException as error:
            failure = repr(error)
            raise
        finally:
            if process is not None:
                if process.poll() is None:
                    process.kill()
                    process.wait(timeout=5)
                process.stdin.close()
                process.stdout.close()
            log.flush()
            ordered = sorted(latencies)
            endpoint = lambda fraction: (
                ordered[min(len(ordered) - 1, int(len(ordered) * fraction))]
                if ordered
                else None
            )
            measured = {
                "p50": statistics.median(ordered) if ordered else None,
                "p95": endpoint(0.95),
                "p99": endpoint(0.99),
                "max": max(ordered) if ordered else None,
            }
            passed = (
                failure is None
                and len(latencies) == args.sequences
                and measured["p99"] < 50
            )
            result = {
                "schema": "caissa-protocol-audit-summary-v2",
                "requested": args.sequences,
                "completed": len(latencies),
                "ponder_completed": ponder_completed,
                "stop_ms": measured,
                "status": "passed" if passed else "failed",
                "failure": failure,
                "seconds": time.monotonic() - started,
                "wall_seconds": time.time() - wall_started,
                "engine_sha256": identity,
                "transcript_sha256": hashlib.sha256(
                    (args.output / "transcript.jsonl").read_bytes()
                ).hexdigest(),
                "engine_exit": process.returncode if process is not None else None,
            }
            atomic(args.output / "summary.json", result)
    print(json.dumps(result))
    return not passed


if __name__ == "__main__":
    raise SystemExit(main())
