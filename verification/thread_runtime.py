"""Independent exact-option UCI state, active-stop, PV and sanitizer reader."""

import hashlib
import json
import math
from pathlib import Path
import re

import chess

from verification.bundle import strict_json


def require(value, reason):
    if not value:
        raise ValueError(reason)


def inspect_events(events, profile, expected):
    require(profile["thread_modes"] == [1, 2, 4, 8] and profile["stop_sample"]["sequences_per_thread_mode"] == 1000 and profile["stop_sample"]["stop_p99_limit_ms_exclusive"] == 50 and profile["instrumented_sample"]["total_fixed_node_searches"] == 64, "thread endpoint was weakened")
    samples, instrumented, pvs = {}, 0, 0
    current, session_count, last_ns = None, 0, 0
    order = [(kind, t) for kind in ["release", "instrumented"] for t in [1, 2, 4, 8]]
    for row in events:
        require(isinstance(row, dict) and type(row.get("session")) is int and row.get("session") == (session_count if row.get("event") == "open" else session_count - 1), "thread session order differs")
        event = row["event"]
        if event == "open":
            require(current is None and session_count < 8, "unclosed or extra native session")
            kind, threads = order[session_count]
            require(row["kind"] == kind and type(row["threads"]) is int and row["threads"] == threads and row["engine_sha256"] == expected[kind + "_engine_sha256"] and row["network_sha256"] == expected["network_sha256"] and row["runtime_sha256"] == (None if kind == "release" else expected["runtime_sha256"]), "native actor, model, runtime or threads differ")
            setup = ["uci", "setoption name Hash value 16", "setoption name Threads value " + str(threads), "setoption name EvalFile value " + expected["network_path"]]
            setup.extend("setoption name " + k + " value " + (str(v).lower() if type(v) is bool else str(v)) for k, v in profile["options"].items() if k != "Hash")
            setup.append("isready")
            current = {"kind": kind, "threads": threads, "setup": setup, "setup_index": 0, "uciok": False, "configured": False, "ready": False, "phase": 0, "sequence": 0, "active": None, "quit": False, "stderr": bytearray(), "runtime_seen": False}
            session_count += 1
            continue
        require(current is not None, "event outside native session")
        c = current
        if event == "close":
            require(c["quit"] and c["active"] is None and c["phase"] == 0 and c["sequence"] == (1000 if c["kind"] == "release" else 16), "incomplete original workload")
            require(type(row["native_exit"]) is int and row["native_exit"] == 0 and row["forced_cleanup"] is False and row["critical_stderr_bytes"] == 0, "native failure or forced cleanup")
            require(row["retained_stderr_bytes"] == len(c["stderr"]) and type(row["dropped_optional_bytes"]) is int and row["dropped_optional_bytes"] >= 0 and row["stderr_bytes"] == len(c["stderr"]) + row["dropped_optional_bytes"], "stderr accounting differs")
            if row["dropped_optional_bytes"] == 0:
                require(hashlib.sha256(c["stderr"]).hexdigest() == row["stderr_sha256"], "stderr digest differs")
            require(c["kind"] != "instrumented" or c["runtime_seen"] is True and row["runtime_seen"] is True, "instrumented runtime witness absent")
            current = None
            continue
        stamp = row.get("ns")
        require(type(stamp) is int and stamp >= last_ns > -1, "invalid or reordered native timestamp")
        last_ns = stamp
        text = row.get("text")
        require(isinstance(text, str) and len(text.encode()) <= 131072, "native text outside bounds")
        if event == "stderr":
            require(text.startswith("dyld["), "critical sanitizer/native diagnostic")
            c["runtime_seen"] |= expected["runtime_path"] in text
            c["stderr"].extend((text + "\n").encode())
            continue
        require(event in {"send", "recv"}, "unknown thread evidence frame")
        if event == "send":
            if not c["configured"]:
                i = c["setup_index"]
                require(i < len(c["setup"]) and text == c["setup"][i], "applied option/setup command differs")
                require(i == 0 or c["uciok"], "options sent before UCI handshake")
                c["setup_index"] += 1
                continue
            total = 1000 if c["kind"] == "release" else 16
            if text == "quit":
                require(c["sequence"] == total and c["phase"] == 0 and c["active"] is None, "premature quit")
                c["quit"] = True
                continue
            require(not c["quit"] and c["sequence"] < total, "extra command after fixed sample")
            phase = c["phase"]
            fen = profile["positions"][c["sequence"] % 4]["fen"]
            expected_command = ["ucinewgame", "position fen " + fen, "isready", "go infinite" if c["kind"] == "release" else "go nodes 2048", "stop"][phase]
            require(text == expected_command, "fixed search command schedule differs")
            if phase == 1:
                c["board"] = chess.Board(fen)
                require(c["board"].is_valid() and not c["board"].is_game_over(), "declared active position invalid or terminal")
            elif phase == 2:
                c["ready"] = False
            elif phase == 3:
                require(c["ready"], "search without readiness barrier")
                c["active"] = {"go": stamp, "stop": None, "witness": None}
            elif phase == 4:
                a = c["active"]
                require(c["kind"] == "release" and a is not None and a["stop"] is None and a["witness"] is not None and stamp > a["witness"], "stop lacks prior active-search witness")
                a["stop"] = stamp
            c["phase"] += 1
            continue
        if text == "uciok":
            require(not c["uciok"] and c["setup_index"] == 1, "unsolicited UCI handshake")
            c["uciok"] = True
        elif text == "readyok":
            if not c["configured"]:
                require(c["setup_index"] == len(c["setup"]), "ready before full applied options")
                c["configured"] = True
            else:
                require(c["phase"] == 3 and not c["ready"], "unexpected readiness response")
                c["ready"] = True
        elif text.startswith(("id ", "option ")):
            require(not c["uciok"], "late UCI declarations")
        elif text.startswith("info string error"):
            raise ValueError("native rejected applied model/options/protocol")
        elif text.startswith("info "):
            a = c["active"]
            require(a is not None and stamp >= a["go"], "stale or unrequested search info")
            words = text.split()
            if "pv" in words:
                board = c["board"].copy()
                for word in words[words.index("pv") + 1:]:
                    move = chess.Move.from_uci(word)
                    require(move in board.legal_moves, "illegal native principal variation")
                    board.push(move)
                pvs += 1
            depth, nodes = re.search(r"\bdepth (\d+)\b", text), re.search(r"\bnodes (\d+)\b", text)
            if depth and nodes and int(depth[1]) >= 2 and int(nodes[1]) > 0 and a["witness"] is None:
                a["witness"] = stamp
        elif text.startswith("bestmove "):
            a = c["active"]
            require(a is not None and c["phase"] == (5 if c["kind"] == "release" else 4), "early, duplicate or unstopped bestmove")
            words = text.split()
            require(len(words) in [2, 4] and words[1] != "0000" and chess.Move.from_uci(words[1]) in c["board"].legal_moves, "illegal native best move")
            if c["kind"] == "release":
                require(a["stop"] is not None and stamp > a["stop"], "bestmove preceded stop")
                samples.setdefault(c["threads"], []).append((stamp - a["stop"]) / 1e6)
            else:
                instrumented += 1
            c["active"], c["phase"] = None, 0
            c["sequence"] += 1
        else:
            raise ValueError("unexpected native response")
    require(current is None and session_count == 8 and instrumented == 64 and set(samples) == {1, 2, 4, 8} and all(len(x) == 1000 for x in samples.values()), "incomplete full thread runtime evidence")

    def percentiles(values):
        ordered = sorted(values)
        return {"count": len(values), "p50": (ordered[(len(values)-1)//2] + ordered[len(values)//2]) / 2, "p95": ordered[min(len(values)-1, math.floor(len(values)*.95))], "p99": ordered[min(len(values)-1, math.floor(len(values)*.99))], "max": ordered[-1]}

    per_thread = {str(k): percentiles(v) for k, v in samples.items()}
    all_stops = percentiles([v for group in samples.values() for v in group])
    require(all(p["p99"] < 50 for p in [all_stops, *per_thread.values()]), "exact-neural stop p99 failed unchanged50ms endpoint")
    return {"status": "passed_exact_neural_thread_runtime_component", "stop_sequences": 4000, "instrumented_searches": 64, "native_sessions": 8, "legal_pvs": pvs, "stop_ms": all_stops, "stop_ms_per_thread": per_thread, "all_native_exits_zero": True, "forced_cleanup": False, "critical_sanitizer_diagnostics": 0, "full_G10_certified": False, "full_acceptance": False}


def verify(scope):
    root = Path(scope["output"])
    profile = strict_json(Path(scope["profile"]).read_bytes())
    summary = strict_json((root / "producer/SUMMARY.json").read_bytes())
    require(summary["status"] == "observed" and summary["failure"] is None and summary["full_acceptance"] is False, "producer did not finish actual workload")
    path = root / "producer/transcript.jsonl"
    require(0 < path.stat().st_size <= scope["journal_limit_bytes"], "transcript outside fixed bound")
    before = path.stat()
    digest, count = hashlib.sha256(), [0]

    def events():
        with path.open("rb") as stream:
            for line in stream:
                require(line.endswith(b"\n") and len(line) <= 262144, "truncated/excessive evidence frame")
                digest.update(line)
                count[0] += 1
                yield strict_json(line)

    expected = {"release_engine_sha256": scope["engine_sha256"], "instrumented_engine_sha256": scope["instrumented_engine_sha256"], "runtime_sha256": scope["instrumented_runtime_sha256"], "network_sha256": scope["network_sha256"], "network_path": scope["network"], "runtime_path": scope["instrumented_runtime"]}
    result = inspect_events(events(), profile, expected)
    after = path.stat()
    require((before.st_ino, before.st_size, before.st_mtime_ns) == (after.st_ino, after.st_size, after.st_mtime_ns) and digest.hexdigest() == summary["transcript_sha256"] and count[0] == summary["frames"] and summary["stop_sequences"] == 4000 and summary["instrumented_searches"] == 64 and summary["sessions"] == 8, "complete transcript/producer binding differs")
    result.update(engine_sha256=scope["engine_sha256"], network_sha256=scope["network_sha256"], instrumented_engine_sha256=scope["instrumented_engine_sha256"], instrumented_runtime_sha256=scope["instrumented_runtime_sha256"], profile_sha256=scope["profile_sha256"], transcript_sha256=digest.hexdigest(), frames=count[0])
    from tools.campaign_process import atomic
    atomic(root / "THREAD_RUNTIME.json", result)
    print(json.dumps(result))
