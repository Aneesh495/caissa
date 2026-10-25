"""Independent legal-move and tactical-only generation replay.

Uses python-chess and an older frozen native executable as separate oracles.
All native responses, including the first mismatch, are retained. No search or
move-generation producer modules are imported.
"""

import argparse
import hashlib
import json
import os
import random
import selectors
import signal
import subprocess
import time
from pathlib import Path

import chess


def sha(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


class Probe:
    def __init__(self, executable, option, deadline):
        self.deadline = deadline
        self.process = subprocess.Popen(
            [
                str(executable.resolve()),
                *(option if isinstance(option, (list, tuple)) else [option]),
            ],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=True,
        )
        self.reader = selectors.DefaultSelector()
        self.writer = selectors.DefaultSelector()
        for stream in [self.process.stdin, self.process.stdout, self.process.stderr]:
            os.set_blocking(stream.fileno(), False)
        self.reader.register(self.process.stdout, selectors.EVENT_READ, "stdout")
        self.reader.register(self.process.stderr, selectors.EVENT_READ, "stderr")
        self.writer.register(self.process.stdin, selectors.EVENT_WRITE)
        self.buffer = b""
        self.stderr = bytearray()

    def request(self, text):
        payload = (text + "\n").encode()
        if len(payload) > 1024 or any(c in text for c in "\r\n\0"):
            raise ValueError("bounded FEN probe input required")
        until = min(time.time() + 3, self.deadline)
        while payload:
            remaining = until - time.time()
            if remaining <= 0 or not self.writer.select(remaining):
                raise TimeoutError("native FEN write deadline")
            try:
                count = os.write(self.process.stdin.fileno(), payload)
                payload = payload[count:]
            except BlockingIOError:
                continue
        while b"\n" not in self.buffer:
            if len(self.buffer) > 16384:
                raise ValueError("native FEN response line ceiling")
            remaining = until - time.time()
            if remaining <= 0:
                raise TimeoutError("native FEN response deadline")
            ready = self.reader.select(remaining)
            if not ready:
                raise TimeoutError("native FEN response deadline")
            for key, _ in ready:
                block = os.read(key.fd, 65536)
                if key.data == "stderr":
                    if not block:
                        self.reader.unregister(key.fileobj)
                    else:
                        self.stderr.extend(block)
                        if len(self.stderr) > 1024 * 1024:
                            raise ValueError("native FEN stderr ceiling")
                    continue
                if not block:
                    raise ValueError("native FEN stdout closed early")
                self.buffer += block
        line, self.buffer = self.buffer.split(b"\n", 1)
        if len(line) > 16384:
            raise ValueError("native FEN response line ceiling")
        self.last_response = line
        return json.loads(line)

    def close(self):
        self.process.stdin.close()
        try:
            self.process.wait(timeout=1)
        except subprocess.TimeoutExpired:
            os.killpg(self.process.pid, signal.SIGTERM)
            try:
                self.process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                os.killpg(self.process.pid, signal.SIGKILL)
                self.process.wait(timeout=3)
        for stream in [self.process.stdout, self.process.stderr]:
            stream.close()
        self.reader.close()
        self.writer.close()


def check_response(board, current, previous):
    expected = sorted(board.uci(move) for move in board.legal_moves)
    tactical = sorted(
        board.uci(move)
        for move in board.legal_moves
        if board.is_capture(move) or move.promotion is not None
    )
    if (
        current.get("moves") != previous.get("moves")
        or sorted(current.get("moves", [])) != expected
        or current.get("key") != previous.get("key")
        or current.get("repetition_key") != previous.get("repetition_key")
        or current.get("fen") != previous.get("fen")
        or sorted(current.get("tactical", [])) != tactical
        or current.get("check") != board.is_check()
        or previous.get("check") != board.is_check()
        or current.get("availability_check") != board.is_check()
        or current.get("any") != bool(expected)
    ):
        raise ValueError("independent full/tactical/availability or identity mismatch")


def atomic(path, value):
    temporary = path.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(value, separators=(",", ":"), allow_nan=False) + "\n"
    )
    temporary.replace(path)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--engine", type=Path, required=True)
    parser.add_argument("--previous", type=Path, required=True)
    parser.add_argument("--positions", type=int, default=100000)
    parser.add_argument("--seed", type=int, default=49979693)
    parser.add_argument("--maximum-seconds", type=int, default=1200)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not 1 <= args.positions <= 1000000 or not 1 <= args.maximum_seconds <= 3600:
        parser.error("finite verification count and wall-time ceiling required")
    args.output.mkdir(parents=True, exist_ok=False)
    started = time.time()
    deadline = started + args.maximum_seconds
    identities = {
        str(path.resolve()): sha(path) for path in [args.engine, args.previous]
    }
    atomic(
        args.output / "CONFIG.json",
        {
            "schema": "caissa-tactical-generation-replay-v1",
            "positions": args.positions,
            "seed": args.seed,
            "maximum_seconds": args.maximum_seconds,
            "deadline_unix": deadline,
            "inputs": identities,
            "oracle": "python-chess " + chess.__version__,
            "full_acceptance": False,
        },
    )
    current = previous = None
    completed = 0
    seen = set()
    games = 0
    rng = random.Random(args.seed)
    board = chess.Board()
    counts = {
        "checked": 0,
        "promotions": 0,
        "en_passant": 0,
        "chess960": 0,
        "terminal": 0,
    }
    try:
        current = Probe(args.engine, "--inspect-tactical", deadline)
        previous = Probe(args.previous, "--inspect", deadline)
        with (args.output / "observations.jsonl").open("x") as stream:
            for i in range(args.positions):
                if time.time() >= deadline:
                    raise TimeoutError(
                        "independent move replay cumulative wall deadline"
                    )
                if board.is_game_over() or board.ply() > 300 or rng.random() < 0.015:
                    games += 1
                    board = (
                        chess.Board.from_chess960_pos(rng.randrange(960))
                        if games % 4 == 0
                        else chess.Board()
                    )
                fen = board.fen(en_passant="fen")
                command = ("960|" if board.chess960 else "") + fen
                response = current.request(command)
                prior = previous.request(command)
                row = {
                    "i": i,
                    "fen": fen,
                    "chess960": board.chess960,
                    "current": response,
                    "previous": prior,
                }
                stream.write(json.dumps(row, separators=(",", ":")) + "\n")
                if stream.tell() > 512 * 1024 * 1024:
                    raise ValueError("independent move evidence byte ceiling")
                check_response(board, response, prior)
                seen.add(
                    (
                        board.chess960,
                        board.board_fen(),
                        board.turn,
                        board.castling_rights,
                        board.ep_square,
                    )
                )
                moves = sorted(board.legal_moves, key=lambda move: board.uci(move))
                counts["checked"] += int(board.is_check())
                counts["chess960"] += int(board.chess960)
                counts["terminal"] += int(not moves)
                counts["promotions"] += sum(
                    move.promotion is not None for move in moves
                )
                counts["en_passant"] += sum(board.is_en_passant(move) for move in moves)
                if moves:
                    board.push(rng.choice(moves))
                completed += 1
                if completed % 1000 == 0:
                    stream.flush()
                    atomic(
                        args.output / "PROGRESS.json",
                        {
                            "completed": completed,
                            "unique": len(seen),
                            "wall_seconds": time.time() - started,
                            "deadline_unix": deadline,
                        },
                    )
        if any(sha(Path(path)) != identity for path, identity in identities.items()):
            raise ValueError("frozen native input changed during replay")
        atomic(
            args.output / "SUMMARY.json",
            {
                "status": "passed",
                "completed": completed,
                "unique": len(seen),
                "counts": counts,
                "wall_seconds": time.time() - started,
                "observations_sha256": sha(args.output / "observations.jsonl"),
                "inputs": identities,
                "full_acceptance": False,
            },
        )
    except BaseException as error:
        atomic(
            args.output / "FAILED.json",
            {
                "status": "failed",
                "completed": completed,
                "wall_seconds": time.time() - started,
                "exception": type(error).__name__,
                "reason": str(error),
            },
        )
        raise
    finally:
        if current is not None:
            current.close()
        if previous is not None:
            previous.close()


if __name__ == "__main__":
    main()
