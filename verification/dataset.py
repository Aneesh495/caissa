"""Independently rebuild prepared targets and features from original game journals.

No imports from training or the native engine are used. The temporary SQLite
index belongs to the verifier and is never written into the evidence dataset.
"""

import argparse
import hashlib
import json
import math
import sqlite3
import tempfile
from pathlib import Path

import chess
import numpy as np

from verification.verify import Rejection, load, terminal


def digest(path):
    value = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            value.update(block)
    return value.hexdigest()


def normalized(board):
    own = board if board.turn == chess.WHITE else board.mirror()
    placement = own.board_fen()
    return hashlib.sha256(placement.encode("ascii")).digest(), own


def feature_rows(board):
    """Reconstruct sparse indices with a board oracle, not the exporter parser."""
    result = np.full((2, 32), 12288, dtype=np.uint16)
    for row, perspective in enumerate((board.turn, not board.turn)):
        king = board.king(perspective)
        if king is None:
            raise Rejection("feature reconstruction has no king")
        king = king if perspective else chess.square_mirror(king)
        bucket = chess.square_rank(king) // 2 * 4 + chess.square_file(king) // 2
        for slot, (square, piece) in enumerate(sorted(board.piece_map().items())):
            oriented = square if perspective else chess.square_mirror(square)
            relative_kind = (
                piece.piece_type - 1 + (0 if piece.color == perspective else 6)
            )
            result[row, slot] = bucket * 768 + relative_kind * 64 + oriented
    return np.sort(result, axis=1)


def holdouts(studies, openings):
    identities, families = set(), set()
    for source in (studies, openings):
        document = load(source)
        for row in document.get("positions", []):
            board = chess.Board(row["fen"], chess960=row.get("chess960", False))
            identities.add(normalized(board)[0])
            for move in row.get("history", []):
                board.push_uci(move)
                identities.add(normalized(board)[0])
        for row in document.get("openings", []):
            board = chess.Board(row.get("fen", chess.STARTING_FEN))
            identities.add(normalized(board)[0])
            for move in row["moves"]:
                board.push_uci(move)
                identities.add(normalized(board)[0])
            if len(row["moves"]) >= 8:
                families.add(
                    hashlib.sha256(" ".join(row["moves"][:8]).encode()).hexdigest()
                )
    return identities, families


def original_game(game):
    """Yield independently verified observations, retaining every legal loss."""
    board = chess.Board()
    by_ply = {}
    for sample in game["positions"]:
        ply = sample["ply"]
        if (
            not isinstance(ply, int)
            or ply in by_ply
            or not 0 <= ply < len(game["moves"])
        ):
            raise Rejection("sample ply is missing, duplicated or outside game")
        by_ply[ply] = sample
    observations = []
    for ply, text in enumerate(game["moves"]):
        sample = by_ply.get(ply)
        if sample is not None:
            if sample["fen"] != board.fen(en_passant="fen"):
                raise Rejection(
                    "sample FEN disagrees with independent original-game replay"
                )
            if (
                not math.isfinite(sample["score_stm"])
                or abs(sample["score_stm"]) > 30000
            ):
                raise Rejection("nonfinite or invalid original-teacher target")
            if not 0 <= sample["nodes"] <= game["budget_nodes"] or sample["depth"] < 0:
                raise Rejection("teacher search metadata violates declared resources")
            observations.append((board.copy(stack=False), sample))
        if board.is_game_over(claim_draw=False):
            raise Rejection(
                "original transcript continued after automatic game termination"
            )
        try:
            move = chess.Move.from_uci(text)
        except ValueError as error:
            raise Rejection("malformed original game move") from error
        if move not in board.legal_moves:
            raise Rejection("illegal original game move")
        board.push(move)
    if game["complete"] != (game["result"] != "*"):
        raise Rejection("original completion/result disagreement")
    if game["termination"] not in {
        "checkmate",
        "stalemate",
        "proven-dead-material",
        "fivefold",
        "seventy-five-move",
        "threefold-claim",
        "fifty-move-claim",
        "ply-limit",
    }:
        raise Rejection("original selfplay used an unsupported adjudication")
    terminal(board, game["termination"], game["result"])
    if not game["complete"]:
        return []
    return observations


def verify_dataset(
    dataset, corpus, studies, openings, require_full=False, scratch=None
):
    dataset, corpus = Path(dataset), Path(corpus)
    manifest = load(dataset / "DATASET.json")
    if manifest.get("schema") != "caissa-dataset-v2" or not manifest.get(
        "functional_deduplication"
    ):
        raise Rejection("full functional-input dataset schema required")
    if manifest["corpus_config"] != load(corpus / "CONFIG.json"):
        raise Rejection("original corpus configuration differs")
    expected_files = {
        f"{split}-{kind}.npy"
        for split in ("train", "validation", "test")
        for kind in ("features", "targets")
    }
    if set(manifest["files"]) != expected_files:
        raise Rejection("prepared array inventory is incomplete or unexpected")
    for filename, expected in manifest["files"].items():
        if Path(filename).name != filename or digest(dataset / filename) != expected:
            raise Rejection("prepared array byte identity differs")
    for path in (studies, openings):
        if manifest["heldout_inputs"].get(str(path)) != digest(path):
            raise Rejection("frozen held-out source differs")
    if digest(dataset / "SOURCE_PAIRS.json") != manifest["source_pairs_sha256"]:
        raise Rejection("original source-pair inventory differs")
    heldout, excluded_families = holdouts(studies, openings)
    source_pairs = load(dataset / "SOURCE_PAIRS.json")
    if [row["pair"] for row in source_pairs] != sorted(
        {row["pair"] for row in source_pairs}
    ):
        raise Rejection("duplicated source pair identity")
    complete_games = unfinished_games = raw_samples = 0
    corpus_hash = hashlib.sha256()
    with tempfile.TemporaryDirectory(
        prefix="caissa-verify-data-", dir=scratch
    ) as temporary:
        connection = sqlite3.connect(Path(temporary) / "replayed.sqlite3")
        connection.execute("PRAGMA journal_mode=OFF")
        connection.execute("PRAGMA cache_size=-131072")
        connection.execute(
            "CREATE TABLE expected (id BLOB PRIMARY KEY, split INTEGER, fen TEXT, outcome REAL, cp REAL, probability REAL, n INTEGER, game TEXT, family TEXT) WITHOUT ROWID"
        )
        connection.execute(
            "CREATE TABLE contributors (id BLOB, game TEXT, n INTEGER, first INTEGER, last INTEGER, PRIMARY KEY(id,game)) WITHOUT ROWID"
        )
        for entry in source_pairs:
            number = entry["pair"]
            source = corpus / f"{number // 256:06d}" / f"{number:09d}.json"
            raw = source.read_bytes()
            actual_hash = hashlib.sha256(raw).hexdigest()
            if actual_hash != entry["sha256"]:
                raise Rejection("original pair bytes differ from prepared lineage")
            corpus_hash.update(bytes.fromhex(actual_hash))
            pair = json.loads(raw)
            if (
                pair["pair"] != number
                or pair["schema"] != "caissa-selfplay-v1"
                or len(pair["games"]) != 2
            ):
                raise Rejection("invalid original paired journal")
            prefix = None
            for reverse, game in enumerate(pair["games"]):
                if game["pair"] != number or game["reverse"] != reverse:
                    raise Rejection("original reversed-color pair identity differs")
                opening = game["moves"][: game["opening_plies"]]
                if prefix is not None and prefix != opening:
                    raise Rejection("original pair did not share its opening")
                prefix = opening
                observations = original_game(game)
                if not game["complete"]:
                    unfinished_games += 1
                    continue
                complete_games += 1
                raw_samples += len(observations)
                family = hashlib.sha256(
                    " ".join(game["moves"][:8]).encode()
                ).hexdigest()
                if family in excluded_families:
                    continue
                split = {0: 1, 1: 2}.get(int(family[:8], 16) % 10, 0)
                white_outcome = {"1-0": 1.0, "0-1": 0.0, "1/2-1/2": 0.5}[game["result"]]
                lineage = f"{number}:{reverse}"
                for board, sample in observations:
                    identity, _ = normalized(board)
                    if identity in heldout:
                        continue
                    outcome = white_outcome if board.turn else 1 - white_outcome
                    cp = float(sample["score_stm"])
                    probability = 1 / (1 + math.exp(-max(-60.0, min(60.0, cp / 400))))
                    previous = connection.execute(
                        "SELECT split FROM expected WHERE id=?", (identity,)
                    ).fetchone()
                    if previous is None:
                        connection.execute(
                            "INSERT INTO expected VALUES(?,?,?,?,?,?,?,?,?)",
                            (
                                identity,
                                split,
                                sample["fen"],
                                outcome,
                                cp,
                                probability,
                                1,
                                lineage,
                                family,
                            ),
                        )
                    elif previous[0] == split:
                        connection.execute(
                            "UPDATE expected SET outcome=outcome+?,cp=cp+?,probability=probability+?,n=n+1 WHERE id=?",
                            (outcome, cp, probability, identity),
                        )
                    else:
                        connection.execute(
                            "UPDATE expected SET split=-1 WHERE id=?", (identity,)
                        )
                    connection.execute(
                        "INSERT INTO contributors VALUES(?,?,?,?,?) ON CONFLICT(id,game) DO UPDATE SET n=n+1,last=excluded.last",
                        (identity, lineage, 1, sample["ply"], sample["ply"]),
                    )
            if number % 256 == 0:
                connection.commit()
        connection.commit()
        if corpus_hash.hexdigest() != manifest["corpus_content_sha256"]:
            raise Rejection("original corpus content chain differs")
        if (
            complete_games != manifest["counts"]["completed_games"]
            or unfinished_games != manifest["counts"]["unfinished_games"]
        ):
            raise Rejection("original completion counts differ")
        counts = {}
        for split, name in enumerate(("train", "validation", "test")):
            expected_count = connection.execute(
                "SELECT count(*) FROM expected WHERE split=?", (split,)
            ).fetchone()[0]
            x = np.load(
                dataset / f"{name}-features.npy", mmap_mode="r", allow_pickle=False
            )
            y = np.load(
                dataset / f"{name}-targets.npy", mmap_mode="r", allow_pickle=False
            )
            if (
                x.dtype != np.uint16
                or x.shape != (expected_count, 2, 32)
                or y.dtype != np.float32
                or y.shape != (expected_count, 3)
            ):
                raise Rejection(
                    "prepared array layout/count differs from original games"
                )
            if manifest["splits"][name] != expected_count:
                raise Rejection(
                    "split declaration differs from actual independent identities"
                )
            with (dataset / f"{name}-identities.jsonl").open() as identities:
                for index, (
                    identity,
                    fen,
                    outcome,
                    cp,
                    probability,
                    n,
                    first_game,
                    first_family,
                ) in enumerate(
                    connection.execute(
                        "SELECT id,fen,outcome,cp,probability,n,game,family FROM expected WHERE split=? ORDER BY id",
                        (split,),
                    )
                ):
                    row = json.loads(next(identities, "{}"))
                    if (
                        row.get("input_id") != identity.hex()
                        or row.get("observations") != n
                    ):
                        raise Rejection("prepared identity/observation lineage differs")
                    canonical = " ".join(
                        chess.Board(fen).fen(en_passant="legal").split()[:4]
                    )
                    if (
                        row.get("first_game") != first_game
                        or row.get("first_family") != first_family
                        or row.get("position_id")
                        != hashlib.sha256(canonical.encode()).hexdigest()
                    ):
                        raise Rejection(
                            "representative position/game/family provenance differs"
                        )
                    reference = feature_rows(chess.Board(fen))
                    if not np.array_equal(np.sort(x[index], axis=1), reference):
                        raise Rejection(
                            "prepared neural features disagree with independent board reconstruction"
                        )
                    target = np.array(
                        (outcome / n, cp / n, probability / n), dtype=np.float32
                    )
                    if not np.array_equal(y[index], target):
                        raise Rejection(
                            "prepared target differs from original outcome/teacher averages"
                        )
                    contributors = [
                        {
                            "game": game,
                            "count": count,
                            "first_ply": first,
                            "last_ply": last,
                        }
                        for game, count, first, last in connection.execute(
                            "SELECT game,n,first,last FROM contributors WHERE id=? ORDER BY game",
                            (identity,),
                        )
                    ]
                    if row.get("contributors") != contributors:
                        raise Rejection("prepared contributor provenance differs")
                if identities.readline():
                    raise Rejection("unexpected extra prepared identity")
            counts[name] = expected_count
        connection.close()
    if require_full:
        if complete_games < 100000 or counts["train"] < 10000000:
            raise Rejection("full original game/training-input floors not met")
        summary = load(corpus / "SUMMARY.json")
        if (
            summary.get("status", "completed") != "completed"
            or summary["pairs"] != manifest["corpus_config"]["requested_pairs"]
            or len(source_pairs) != summary["pairs"]
        ):
            raise Rejection(
                "full original corpus did not complete its frozen pair request"
            )
    return {
        "status": "passed",
        "profile": "full-data-replay" if require_full else "diagnostic-data-replay",
        "source_pairs": len(source_pairs),
        "completed_games": complete_games,
        "unfinished_games": unfinished_games,
        "raw_samples": raw_samples,
        "independently_rebuilt_splits": counts,
        "dataset_sha256": digest(dataset / "DATASET.json"),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("dataset", type=Path)
    parser.add_argument("corpus", type=Path)
    parser.add_argument("--studies", type=Path, default=Path("config/studies.json"))
    parser.add_argument(
        "--openings", type=Path, default=Path("config/strength-openings.json")
    )
    parser.add_argument("--require-full", action="store_true")
    parser.add_argument("--scratch", type=Path)
    args = parser.parse_args()
    try:
        result = verify_dataset(
            args.dataset,
            args.corpus,
            args.studies,
            args.openings,
            args.require_full,
            args.scratch,
        )
        print(json.dumps(result))
        return 0
    except (ValueError, KeyError, OSError, sqlite3.Error) as error:
        print(json.dumps({"status": "rejected", "reason": str(error)}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
