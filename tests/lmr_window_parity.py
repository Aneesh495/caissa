"""Check that PVS-enabled frozen search results survive the LMR recovery repair."""

import argparse
import contextlib
import json
import time
from pathlib import Path

from verification.acquisition import sha
from verification.evaluation_cost import parse
from verification.native_session import NativeSession


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--old", type=Path, required=True)
    parser.add_argument("--new", type=Path, required=True)
    parser.add_argument("--old-sha256", required=True)
    parser.add_argument("--new-sha256", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    engines = {"old": args.old, "new": args.new}
    expected = {"old": args.old_sha256, "new": args.new_sha256}
    assert {key: sha(path) for key, path in engines.items()} == expected
    positions = Path("config/performance.json")
    positions_sha = "8a27cea07ff367e7c991a5c855a1d4620a7f43b8578f95309e8d50f0ad63fcfe"
    assert sha(positions) == positions_sha
    cases = json.loads(positions.read_text())["positions"]
    network = Path("models/residual-prefix-diagnostic.cai").resolve()
    network_sha = sha(network)
    args.output.mkdir(parents=True, exist_ok=False)
    started = time.time()
    deadline = started + 120
    pairs = 0
    with (args.output / "observations.jsonl").open("x") as stream:
        for weight in [0, 10, 100]:
            options = {
                "Threads": 1,
                "Hash": 16,
                "MultiPV": 1,
                "PVS": True,
                "Search Stats": True,
                "Evaluation Cache": True,
                "Tactical Generation": True,
            }
            if weight:
                options.update({"EvalFile": str(network), "Neural Weight": weight})
            options["Use Neural"] = weight > 0
            with contextlib.ExitStack() as stack:
                clients = {
                    key: stack.enter_context(NativeSession(path, options, deadline))
                    for key, path in engines.items()
                }
                for case in cases:
                    for budget in [5000, 25000]:
                        observed = {}
                        for key, client in clients.items():
                            lines = client.search(case["fen"], budget)
                            best, details = parse(lines, case["fen"])
                            stream.write(
                                json.dumps(
                                    {
                                        "actor": key,
                                        "weight": weight,
                                        "position": case["id"],
                                        "fen": case["fen"],
                                        "nodes": budget,
                                        "options": options,
                                        "bestmove": best,
                                        "observed": details,
                                        "uci": lines,
                                    }
                                )
                                + "\n"
                            )
                            stream.flush()
                            work = {
                                k: v
                                for k, v in details["stats"].items()
                                if k not in ["elapsed_ms", "eval_ns"]
                            }
                            logical = {
                                k: v
                                for k, v in details.items()
                                if k not in ["stats", "time", "nps", "hashfull"]
                            }
                            observed[key] = (best, work, logical)
                        assert observed["old"] == observed["new"], (
                            weight,
                            case["id"],
                            budget,
                            observed,
                        )
                        pairs += 1
    assert pairs == 48 and {key: sha(path) for key, path in engines.items()} == expected
    assert sha(network) == network_sha and sha(positions) == positions_sha
    result = {
        "status": "passed",
        "pairs": pairs,
        "actual_native_queries": 96,
        "engine_identities": expected,
        "network_sha256": network_sha,
        "positions_sha256": positions_sha,
        "seconds": time.time() - started,
        "observations_sha256": sha(args.output / "observations.jsonl"),
        "scope": "PVS enabled; old diagnostic network only; no Elo or full-source acceptance claim",
        "full_acceptance": False,
    }
    (args.output / "SUMMARY.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result))


if __name__ == "__main__":
    main()
