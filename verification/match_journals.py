"""Independent agreement of paired records, game journals and exported PGNs.

This checks the actual artifacts, not a saved status or checksum receipt. It
does not execute engines, infer a rating or replace the full strength sample.
"""

import argparse
import io
import json
import math
import time
from pathlib import Path

import chess
import chess.pgn

from verification.bundle import strict_json
from verification.draw_history import typed_equal
from verification.strength import validate_observations
from verification.verify import Rejection, replay_game


def require(condition, reason):
    if not condition:
        raise Rejection(reason)


def regular(path, maximum):
    require(
        path.is_file() and not path.is_symlink() and 0 < path.stat().st_size <= maximum,
        "match journal missing, linked or excessive: " + path.name,
    )
    return path.read_bytes()


def verify(campaign, *, maximum_seconds=600, tick=None):
    from tools.heuristic_study import avoid_decisive_matches

    avoid_decisive_matches()
    require(
        type(maximum_seconds) in {int, float}
        and math.isfinite(maximum_seconds)
        and 0 < maximum_seconds <= 3600,
        "finite match-journal verification ceiling required",
    )
    campaign = Path(campaign)
    require(
        campaign.is_dir() and not campaign.is_symlink(),
        "match campaign must be a real directory",
    )
    active, deadline = time.monotonic(), time.time() + maximum_seconds

    def check():
        if tick is not None:
            tick()
        require(
            time.time() < deadline and time.monotonic() - active < maximum_seconds,
            "match-journal verification deadline exhausted",
        )

    identity = strict_json(regular(campaign / "CONFIG.json", 4 * 1024 * 1024))
    config = identity["config"]
    pairs = config.get("pairs")
    require(
        type(pairs) is int and 1 <= pairs <= 2000,
        "match-journal pair count outside bound",
    )
    for folder in ["pairs", "games"]:
        require(
            (campaign / folder).is_dir() and not (campaign / folder).is_symlink(),
            "match journal directory missing or linked",
        )
    expected_pairs = {f"{pair:06d}.json" for pair in range(pairs)}
    expected_games = {
        f"{pair:06d}-{reverse}.{extension}"
        for pair in range(pairs)
        for reverse in [0, 1]
        for extension in ["json", "pgn"]
    }
    require(
        {p.name for p in (campaign / "pairs").iterdir()} == expected_pairs,
        "paired journal file inventory differs",
    )
    require(
        {p.name for p in (campaign / "games").iterdir()} == expected_games,
        "game/PGN journal file inventory differs",
    )
    completed = played = 0
    for number in range(pairs):
        check()
        pair = strict_json(
            regular(campaign / "pairs" / f"{number:06d}.json", 64 * 1024 * 1024)
        )
        require(
            pair.get("schema") == "caissa-arena-pair-v1"
            and type(pair.get("pair")) is int
            and pair["pair"] == number
            and type(pair.get("games")) is list
            and len(pair["games"]) == 2,
            "paired journal identity or reversed-game inventory differs",
        )
        for reverse, embedded in enumerate(pair["games"]):
            check()
            stem = f"{number:06d}-{reverse}"
            record = strict_json(
                regular(campaign / "games" / (stem + ".json"), 64 * 1024 * 1024)
            )
            require(
                typed_equal(record, embedded),
                "separate game journal differs from paired record",
            )
            require(
                record.get("schema") == "caissa-arena-game-v1"
                and type(record.get("pair")) is int
                and type(record.get("reverse")) is int
                and record["pair"] == number
                and record["reverse"] == reverse
                and record.get("opening_id") == pair["opening_id"]
                and record.get("candidate_color")
                == ("white" if reverse == 0 else "black"),
                "game journal identity or candidate color differs",
            )
            require(
                type(record.get("moves")) is list
                and len(record["moves"]) <= config["max_plies"],
                "game journal ply ceiling differs",
            )
            replay_game(record)
            validate_observations(record, config, require_requests=True)
            pgn_text = regular(
                campaign / "games" / (stem + ".pgn"), 4 * 1024 * 1024
            ).decode("utf-8")
            stream = io.StringIO(pgn_text)
            game = chess.pgn.read_game(stream)
            require(
                game is not None and not game.errors,
                "match PGN is malformed or has illegal notation",
            )
            require(
                chess.pgn.read_game(stream) is None,
                "match PGN contains another unrecorded game",
            )
            require(
                game.headers.get("Variant", "Standard") == "Standard",
                "match PGN changed the rule variant",
            )
            expected_board = chess.Board(record["initial"])
            require(
                game.board().fen(en_passant="legal")
                == expected_board.fen(en_passant="legal"),
                "match PGN initial board differs",
            )
            actors = (
                [config["candidate"], config["opponent"]]
                if reverse == 0
                else [config["opponent"], config["candidate"]]
            )
            for key, value in {
                "White": actors[0]["name"],
                "Black": actors[1]["name"],
                "Result": record["result"],
                "Termination": record["termination"],
                "OpeningId": record["opening_id"],
            }.items():
                require(
                    game.headers.get(key) == value,
                    "match PGN header differs from actual record: " + key,
                )
            replay = game.board()
            moves = []
            node = game
            while node.variations:
                require(
                    len(node.variations) == 1,
                    "match PGN contains an unrecorded variation",
                )
                node = node.variations[0]
                text = replay.uci(node.move)
                require(
                    node.move in replay.legal_moves, "match PGN main line is illegal"
                )
                replay.push(node.move)
                moves.append(text)
                require(
                    len(moves) <= config["max_plies"],
                    "match PGN main line exceeds the ply ceiling",
                )
            require(
                moves == record["moves"],
                "match PGN played moves differ from the journal",
            )
            completed += 1
            played += len(moves)
    return {
        "status": "passed",
        "pairs": pairs,
        "game_journals": completed,
        "pgn_files": completed,
        "played_plies": played,
        "elapsed_seconds": time.monotonic() - active,
        "scope": "Actual pair/game/PGN consistency and independent legality, outcome and request replay only",
        "full_strength_sample_certified": False,
        "full_acceptance": False,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("campaign", type=Path)
    parser.add_argument("--maximum-seconds", type=float, default=600)
    args = parser.parse_args()
    try:
        print(json.dumps(verify(args.campaign, maximum_seconds=args.maximum_seconds)))
    except (ValueError, KeyError, OSError, TypeError) as error:
        print(
            json.dumps(
                {"status": "rejected", "reason": str(error), "full_acceptance": False}
            )
        )
        raise SystemExit(1)


if __name__ == "__main__":
    main()
