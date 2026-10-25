"""Re-execute retained search-context cost cases using independent transport."""

import contextlib
import hashlib
import json
import statistics
import sys
import time
from pathlib import Path

from verification.evaluation_cost import parse
from verification.native_session import NativeSession


def main():
    evidence, output = map(Path, sys.argv[1:])
    output.mkdir(parents=True, exist_ok=False)
    config = json.loads((evidence / "COST_CONFIG.json").read_text())
    summary = json.loads((evidence / "COST_SUMMARY.json").read_text())
    digest = lambda path: hashlib.sha256(Path(path).read_bytes()).hexdigest()
    for path, identity in config["inputs"].items():
        if digest(path) != identity:
            raise ValueError("cost input differs from retained identity")
    raw = evidence / "cost-observations.jsonl"
    if raw.stat().st_size > 32 * 1024**2 or digest(raw) != summary["raw_sha256"]:
        raise ValueError("cost observation identity or size differs")
    rows = [json.loads(line) for line in raw.read_text().splitlines()]
    if len(rows) != 180 or summary["searches"] != 180:
        raise ValueError("cost sample differs")
    cases = {row["id"]: row for row in config["positions"]}
    by_mode = {}
    for row in rows:
        key = (row["repeat"], row["position"], row["mode"], row["engine"])
        if key in by_mode:
            raise ValueError("duplicated cost observation")
        by_mode[key] = row
    expected = {(r, p, m, e) for r in range(3) for p in cases for m in ("classical", "mixture", "neural") for e in ("previous", "incremental")}
    if set(by_mode) != expected:
        raise ValueError("cost inventory is incomplete")
    for mode in ("classical", "mixture", "neural"):
        ratios = [by_mode[r, p, mode, "incremental"]["roundtrip_ms"] / by_mode[r, p, mode, "previous"]["roundtrip_ms"] for r in range(3) for p in cases]
        if ratios != summary["ratios"][mode]["all_ratios"] or statistics.median(ratios) != summary["ratios"][mode]["median_incremental_over_previous_ms"]:
            raise ValueError("cost summary differs from retained observations")
    deadline = time.time() + 180
    binaries = {"previous": Path("build-tactical/caissa"), "incremental": Path("build-search-context/caissa")}
    model = Path("models/residual-prefix-diagnostic.cai").resolve()
    with contextlib.ExitStack() as stack, (output / "replay.jsonl").open("x") as stream:
        sessions = {}
        for label, binary in binaries.items():
            for mode, weight in (("classical", 0), ("mixture", 10), ("neural", 100)):
                options = {"Threads": 1, "Hash": 16, "Search Stats": True, "Evaluation Cache": True, "Tactical Generation": True}
                if weight:
                    options.update({"EvalFile": str(model), "Use Neural": True, "Neural Weight": weight})
                sessions[label, mode] = stack.enter_context(contextlib.closing(NativeSession(binary, options, deadline)))
        for row in rows:
            case = cases[row["position"]]
            fen = case.get("resulting_fen", case["fen"])
            move, observed = parse(row["uci"], fen)
            if move != row["bestmove"] or observed != row["observed"]:
                raise ValueError("cost metadata differs from actual raw response")
            session = sessions[row["engine"], row["mode"]]
            session.send("ucinewgame")
            session.ready()
            command = "position fen " + case["fen"]
            if case.get("moves"):
                command += " moves " + " ".join(case["moves"])
            session.send(command)
            session.send("go nodes 50000")
            actual = session.until("bestmove ")
            new_move, new_observed = parse(actual, fen)
            if new_move != move:
                raise ValueError("native replay best move changed")
            stable = lambda value: {key: item for key, item in value.items() if key not in ("time", "nps", "hashfull", "stats")}
            stats = lambda value: {key: item for key, item in value["stats"].items() if key not in ("elapsed_ms", "eval_ns")}
            if stable(observed) != stable(new_observed) or stats(observed) != stats(new_observed):
                raise ValueError("native replay work, score, or PV changed")
            stream.write(json.dumps({"key": [row[k] for k in ("repeat", "position", "mode", "engine")], "position_command": command, "uci": actual}, separators=(",", ":")) + "\n")
    if digest(raw) != summary["raw_sha256"]:
        raise ValueError("cost observations changed during replay")
    report = {"status": "passed", "independently_reexecuted_queries": len(rows), "original_raw_sha256": digest(raw), "replay_sha256": digest(output / "replay.jsonl"), "full_acceptance": False, "scope": "Independent parser and native transport reproduce all work counters, scores, PVs and best moves; timings remain descriptive loaded-host observations, not an Elo estimate"}
    (output / "SUMMARY.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report))


if __name__ == "__main__":
    main()
