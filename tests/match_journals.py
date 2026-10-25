"""Rehashed contradictory journals through the actual independent CLI.

Uses an existing real native CI arena. It does not generate a strength sample.
"""

import argparse
import hashlib
import io
import json
import shutil
import subprocess
import sys
from pathlib import Path

import chess.pgn

from tools.campaign_process import atomic


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--campaign", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    results = []

    def run(name, root, reason=None):
        argv = [
            sys.executable,
            "-m",
            "verification.match_journals",
            str(root),
            "--maximum-seconds",
            "30",
        ]
        result = subprocess.run(argv, capture_output=True, text=True, timeout=35)
        (args.output / (name + ".log")).write_text(result.stdout + result.stderr)
        value = json.loads(result.stdout)
        if reason is None:
            assert (
                result.returncode == 0
                and value["game_journals"] == 4
                and value["full_strength_sample_certified"] is False
            ), (name, value)
        else:
            assert result.returncode == 1 and reason in value["reason"], (
                name,
                result.returncode,
                value,
                result.stderr,
            )
        results.append(
            {
                "case": name,
                "command": argv,
                "actual_exit": result.returncode,
                "observed": value,
            }
        )

    run("positive", args.campaign)
    for case in [
        "split-record",
        "pgn-result",
        "pgn-colors",
        "pgn-moves",
        "bool-identity",
        "incorrect-draw",
        "illegal-pv",
        "missing-pgn",
        "extra-pair",
    ]:
        root = args.output / case
        shutil.copytree(args.campaign, root)
        pair_path = root / "pairs/000000.json"
        game_path = root / "games/000000-0.json"
        pgn_path = game_path.with_suffix(".pgn")
        pair = json.loads(pair_path.read_text())
        record = json.loads(game_path.read_text())
        if case == "split-record":
            record["result"] = "0-1" if record["result"] != "0-1" else "1-0"
            atomic(game_path, record)
        elif case.startswith("pgn-"):
            game = chess.pgn.read_game(io.StringIO(pgn_path.read_text()))
            assert game is not None
            if case == "pgn-result":
                game.headers["Result"] = (
                    "0-1" if game.headers["Result"] != "0-1" else "1-0"
                )
            elif case == "pgn-colors":
                game.headers["White"], game.headers["Black"] = (
                    game.headers["Black"],
                    game.headers["White"],
                )
            else:
                assert game.variations
                game.variations = []
            pgn_path.write_text(str(game) + "\n")
        elif case == "bool-identity":
            pair["pair"] = False
            atomic(pair_path, pair)
        elif case == "incorrect-draw":
            record["termination"] = "seventy-five-move"
            record["result"] = "1/2-1/2"
            pair["games"][0] = record
            atomic(pair_path, pair)
            atomic(game_path, record)
            game = chess.pgn.read_game(io.StringIO(pgn_path.read_text()))
            game.headers["Termination"] = record["termination"]
            game.headers["Result"] = record["result"]
            pgn_path.write_text(str(game) + "\n")
        elif case == "illegal-pv":
            row = next(r for r in record["observations"] if "ply" in r and "uci" in r)
            row["uci"].insert(0, "info depth 1 score cp 0 nodes 1 time 0 pv a1a8")
            pair["games"][0] = record
            atomic(pair_path, pair)
            atomic(game_path, record)
        elif case == "missing-pgn":
            pgn_path.unlink()
        elif case == "extra-pair":
            shutil.copy2(pair_path, root / "pairs/999999.json")
        atomic(
            root / "REHASHED.json",
            {
                str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in sorted(root.rglob("*"))
                if p.is_file()
            },
        )
        reason = {
            "split-record": "differs from paired record",
            "pgn-result": "header differs",
            "pgn-colors": "header differs",
            "pgn-moves": "played moves differ",
            "bool-identity": "paired journal identity",
            "incorrect-draw": "invalid terminal or draw claim",
            "illegal-pv": "principal variation is illegal",
            "missing-pgn": "file inventory differs",
            "extra-pair": "file inventory differs",
        }[case]
        run(case, root, reason)
    atomic(
        args.output / "CONTROLS.json",
        {
            "status": "passed",
            "cases": results,
            "full_strength_sample_certified": False,
            "full_acceptance": False,
        },
    )
    print(
        json.dumps(
            {
                "status": "passed",
                "positive_games": 4,
                "semantic_rejections": 9,
                "full_acceptance": False,
            }
        )
    )


if __name__ == "__main__":
    main()
