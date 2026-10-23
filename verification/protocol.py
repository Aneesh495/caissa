"""Read-only UCI transcript state, legal PV and stop-latency reconstruction.

This checker never imports the producer or executes its native executable.
Its full flag enforces the G04 sample, not whole-project acceptance.
"""

import argparse
import collections
import hashlib
import json
import math
import statistics
from pathlib import Path

import chess


def require(condition, reason):
    if not condition:
        raise ValueError(reason)


def read_json(text):
    def bad(value):
        raise ValueError("nonfinite protocol JSON: " + value)

    def unique(pairs):
        result = {}
        for key, value in pairs:
            require(key not in result, "duplicate protocol JSON key")
            result[key] = value
        return result

    return json.loads(text, parse_constant=bad, object_pairs_hook=unique)


def digest(path):
    result = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(block)
    return result.hexdigest()


def verify(root, expected_engine, full=False):
    config = read_json((root / "CONFIG.json").read_text())
    summary = read_json((root / "summary.json").read_text())
    require(
        config["schema"] == "caissa-protocol-audit-v2", "unsupported protocol campaign"
    )
    require(
        summary["schema"] == "caissa-protocol-audit-summary-v2",
        "unsupported protocol result",
    )
    require(
        config["engine_sha256"] == summary["engine_sha256"] == expected_engine,
        "protocol executable identity differs",
    )
    requested = config["requested"]
    require(
        type(requested) is int and 1 <= requested <= 100000,
        "protocol workload outside bounds",
    )
    require(
        not full or requested >= 10000, "full protocol workload below 10000 sequences"
    )
    require(
        config["ponder_sequences"] == 100
        and config["stop_p99_limit_ms_exclusive"] == 50,
        "protocol endpoint was weakened",
    )
    require(1 <= config["maximum_seconds"] <= 3600, "protocol duration outside bounds")
    require(
        config["maximum_transcript_bytes"] <= 512 * 1024 * 1024,
        "protocol byte ceiling was weakened",
    )
    path = root / "transcript.jsonl"
    require(
        0 < path.stat().st_size <= config["maximum_transcript_bytes"],
        "protocol transcript size outside bounds",
    )
    require(
        digest(path) == summary["transcript_sha256"], "protocol transcript hash differs"
    )
    bad_commands = {
        "setoption name Absent value true",
        "go nodes -1",
        "position fen garbage",
        "setoption name Threads value 99",
        "go movetime 999999999999999999999999999",
        "position startpos moves a1a8",
    }
    ordinary_go = {"go infinite", "go nodes 200", "go movetime 50", "go depth 5"}
    invalid = collections.Counter()
    go_counts = collections.Counter()
    threads = set()
    handshake = False
    handshake_pending = False
    readiness = 0
    pending_errors = 0
    error_count = 0
    board = None
    active = None
    stop_latencies = []
    ponder_latencies = []
    pv_count = 0
    bestmoves = 0
    last_stamp = -1
    quit_seen = False
    rows = 0
    with path.open() as stream:
        for raw in stream:
            rows += 1
            require(rows <= 2000000 and len(raw) <= 20000, "protocol record ceiling")
            row = read_json(raw)
            sending = "send" in row
            require(
                set(row) == {"send" if sending else "receive", "ns"},
                "unknown protocol event fields",
            )
            stamp = row["ns"]
            require(
                type(stamp) is int and stamp >= last_stamp and stamp >= 0,
                "protocol timestamps are not monotonic integers",
            )
            last_stamp = stamp
            text = row["send" if sending else "receive"]
            require(
                isinstance(text, str) and not any(c in text for c in "\r\n\0"),
                "invalid protocol event line",
            )
            require(not quit_seen, "protocol event after quit")
            if sending:
                if text in bad_commands or text == "X" * 9000:
                    require(active is None, "negative control overlapped a search")
                    invalid[text] += 1
                    pending_errors += 1
                elif text == "uci":
                    require(
                        not handshake and not handshake_pending,
                        "duplicate UCI handshake",
                    )
                    handshake_pending = True
                elif text == "isready":
                    readiness += 1
                elif text.startswith("setoption name Hash value "):
                    require(
                        active is None and text.rsplit(" ", 1)[1] in ["1", "2"],
                        "invalid hash resize",
                    )
                elif text.startswith("setoption name Threads value "):
                    count = int(text.rsplit(" ", 1)[1])
                    require(
                        active is None and count in [1, 2, 4, 8],
                        "invalid thread setting",
                    )
                    threads.add(count)
                elif text.startswith("position "):
                    require(active is None, "position changed during active search")
                    if text == "position startpos":
                        board = chess.Board()
                    else:
                        require(
                            text.startswith("position fen "),
                            "unsupported position command",
                        )
                        board = chess.Board(text[13:])
                        require(board.is_valid(), "invalid protocol board")
                elif text in ordinary_go or text == "go ponder depth 1":
                    require(
                        handshake
                        and readiness == 0
                        and active is None
                        and board is not None,
                        "search started without handshake, readiness or an idle position",
                    )
                    go_counts[text] += 1
                    active = {
                        "board": board.copy(stack=True),
                        "go": text,
                        "start": stamp,
                        "stop": None,
                        "hit": None,
                    }
                elif text == "stop":
                    require(
                        active is not None
                        and active["stop"] is None
                        and active["go"] in ordinary_go,
                        "unmatched stop",
                    )
                    active["stop"] = stamp
                elif text == "ponderhit":
                    require(
                        active is not None
                        and active["go"] == "go ponder depth 1"
                        and active["hit"] is None,
                        "unmatched ponderhit",
                    )
                    active["hit"] = stamp
                elif text == "quit":
                    require(
                        active is None and readiness == 0 and pending_errors == 0,
                        "quit with incomplete protocol work",
                    )
                    quit_seen = True
                else:
                    raise ValueError("unexpected protocol command: " + text[:100])
            elif text == "uciok":
                require(handshake_pending and not handshake, "unsolicited uciok")
                handshake = True
                handshake_pending = False
            elif text == "readyok":
                require(
                    readiness > 0 and pending_errors == 0,
                    "unsolicited readyok or missing negative-control error",
                )
                readiness -= 1
            elif text.startswith("info string error "):
                require(pending_errors > 0, "unexpected native protocol error")
                pending_errors -= 1
                error_count += 1
            elif text.startswith("bestmove "):
                require(active is not None, "unsolicited or duplicate bestmove")
                fields = text.split()
                require(
                    len(fields) == 2 or (len(fields) == 4 and fields[2] == "ponder"),
                    "unexpected bestmove fields",
                )
                current = active["board"]
                if fields[1] == "0000":
                    require(
                        current.is_game_over(claim_draw=False),
                        "null bestmove in playable position",
                    )
                else:
                    require(
                        chess.Move.from_uci(fields[1]) in current.legal_moves,
                        "illegal protocol bestmove",
                    )
                if len(fields) == 4:
                    require(fields[1] != "0000", "ponder reply after null bestmove")
                    after = current.copy(stack=True)
                    after.push(chess.Move.from_uci(fields[1]))
                    require(
                        chess.Move.from_uci(fields[3]) in after.legal_moves,
                        "illegal protocol ponder reply",
                    )
                if active["go"] in ordinary_go:
                    require(
                        active["stop"] is not None,
                        "bestmove has no measured stop request",
                    )
                    stop_latencies.append((stamp - active["stop"]) / 1e6)
                else:
                    require(
                        active["hit"] is not None, "ponder result preceded ponderhit"
                    )
                    latency = (stamp - active["hit"]) / 1e6
                    require(
                        latency < 1000,
                        "ponderhit exceeded the frozen response deadline",
                    )
                    ponder_latencies.append(latency)
                bestmoves += 1
                active = None
            elif text.startswith("info ") and " pv " in text:
                require(active is not None, "principal variation outside a search")
                replay = active["board"].copy(stack=True)
                variation = text.split(" pv ", 1)[1].split()
                require(variation, "empty principal variation")
                for word in variation:
                    move = chess.Move.from_uci(word)
                    require(
                        move in replay.legal_moves,
                        "illegal protocol principal variation",
                    )
                    replay.push(move)
                pv_count += 1
            elif text.startswith("option name ") or text.startswith("id "):
                require(handshake_pending, "option or identity outside handshake")
            else:
                require(text.startswith("info "), "unrecognized protocol response")
    require(
        quit_seen
        and active is None
        and handshake
        and readiness == 0
        and pending_errors == 0,
        "incomplete protocol lifecycle",
    )
    require(
        len(stop_latencies) == requested and len(ponder_latencies) == 100,
        "missing protocol sequences",
    )
    for command in bad_commands:
        require(
            invalid[command] == (requested + 22) // 23,
            "missing adversarial command coverage",
        )
    require(invalid["X" * 9000] == 1, "missing oversized-command control")
    require(
        not full or threads == {1, 2, 4, 8}, "full protocol thread inventory incomplete"
    )
    require(
        not full or ordinary_go.issubset(go_counts),
        "full protocol search-mode inventory incomplete",
    )
    ordered = sorted(stop_latencies)
    measured = {
        "p50": statistics.median(ordered),
        "p95": ordered[int(len(ordered) * 0.95)],
        "p99": ordered[int(len(ordered) * 0.99)],
        "max": max(ordered),
    }
    for key, value in measured.items():
        require(
            type(summary["stop_ms"][key]) in [int, float]
            and math.isfinite(summary["stop_ms"][key])
            and abs(summary["stop_ms"][key] - value) < 1e-12,
            "stop-latency summary differs: " + key,
        )
    require(
        summary["requested"] == summary["completed"] == requested
        and summary["ponder_completed"] == 100,
        "protocol summary counts differ",
    )
    require(
        measured["p99"] < 50
        and summary["status"] == "passed"
        and summary["failure"] is None
        and summary["engine_exit"] == 0,
        "protocol endpoint or lifecycle failed",
    )
    return {
        "status": "passed",
        "scope": "full G04 transcript sample" if full else "diagnostic protocol replay",
        "completed": len(stop_latencies),
        "ponder_completed": len(ponder_latencies),
        "legal_pvs": pv_count,
        "bestmoves": bestmoves,
        "negative_control_errors": error_count,
        "threads_observed": sorted(threads),
        "stop_ms": measured,
        "transcript_sha256": digest(path),
        "engine_sha256": expected_engine,
        "full_acceptance": False,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("evidence", type=Path)
    parser.add_argument("--engine-sha256", required=True)
    parser.add_argument("--full", action="store_true")
    args = parser.parse_args()
    try:
        result = verify(args.evidence, args.engine_sha256, args.full)
        print(json.dumps(result, allow_nan=False))
        return 0
    except (ValueError, KeyError, OSError, TypeError) as error:
        print(json.dumps({"status": "rejected", "reason": str(error)}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
