"""Replay, lineage splitting, functional-input deduplication and held-out screening."""

import argparse, hashlib, json, math, sqlite3, time, fcntl
from pathlib import Path
import chess
import numpy as np
from training.corpus import atomic_json, digest
from training.features import features, input_identity


def verify_game(g):
    b = chess.Board()
    samples = {s["ply"]: s for s in g["positions"]}
    if len(samples) != len(g["positions"]):
        raise ValueError("duplicate ply record")
    for ply, text in enumerate(g["moves"]):
        if ply in samples and samples[ply]["fen"] != b.fen(en_passant="fen"):
            raise ValueError("sample does not match independent replay")
        m = chess.Move.from_uci(text)
        if m not in b.legal_moves:
            raise ValueError(f"illegal corpus move {text} at ply {ply}")
        b.push(m)
    reason = g["termination"]
    result = g["result"]
    if not g["complete"]:
        if result != "*" or reason != "ply-limit":
            raise ValueError("unfinished result provenance")
        return False
    legal_reason = {
        "checkmate": b.is_checkmate(),
        "stalemate": b.is_stalemate(),
        "fivefold": b.is_fivefold_repetition(),
        "seventy-five-move": b.is_seventyfive_moves(),
        "proven-dead-material": b.is_insufficient_material(),
        "threefold-claim": b.is_repetition(3),
        "fifty-move-claim": b.halfmove_clock >= 100 and bool(b.legal_moves),
    }
    if not legal_reason.get(reason, False):
        raise ValueError("incorrect terminal/draw claim " + reason)
    expected = ("0-1" if b.turn else "1-0") if reason == "checkmate" else "1/2-1/2"
    if result != expected:
        raise ValueError("result color inconsistent with replay")
    return True


def canonical(fen):
    b = chess.Board(fen)
    return " ".join(b.fen(en_passant="legal").split()[:4])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("corpus", type=Path)
    ap.add_argument("output", type=Path)
    ap.add_argument("--studies", type=Path, default=Path("config/studies.json"))
    ap.add_argument(
        "--openings", type=Path, default=Path("config/strength-openings.json")
    )
    ap.add_argument("--resume", action="store_true")
    ap.add_argument("--follow", action="store_true")
    a = ap.parse_args()
    if a.resume and not (a.output / "identities.sqlite3").exists():
        raise ValueError("no preparation transaction exists to resume")
    a.output.mkdir(parents=True, exist_ok=a.resume)
    writer = (a.output / "PREPARE.lock").open("a")
    fcntl.flock(writer.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    if (a.output / "DATASET.json").exists():
        raise ValueError("prepared dataset is already complete and immutable")
    heldout = set()
    heldout_families = set()
    heldout_inputs = {}
    for source in [a.studies, a.openings]:
        if not source.exists():
            continue
        heldout_inputs[str(source)] = digest(source)
        document = json.loads(source.read_text())
        for item in document.get("positions", []):
            board = chess.Board(item["fen"], chess960=item.get("chess960", False))
            heldout.add(input_identity(board.fen(en_passant="fen")))
            for text in item.get("history", []):
                board.push_uci(text)
                heldout.add(input_identity(board.fen(en_passant="fen")))
        for opening in document.get("openings", []):
            board = chess.Board(opening.get("fen", chess.STARTING_FEN))
            path = []
            heldout.add(input_identity(board.fen(en_passant="fen")))
            for text in opening["moves"]:
                board.push_uci(text)
                path.append(text)
                heldout.add(input_identity(board.fen(en_passant="fen")))
            if len(path) >= 8:
                heldout_families.add(
                    hashlib.sha256(" ".join(path[:8]).encode()).hexdigest()
                )
    db = sqlite3.connect(a.output / "identities.sqlite3")
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA cache_size=-131072")
    db.execute(
        "CREATE TABLE IF NOT EXISTS positions (input BLOB PRIMARY KEY, position_id BLOB, split INTEGER, fen TEXT, outcome REAL, teacher_cp REAL, teacher_probability REAL, n INTEGER, min_outcome REAL, max_outcome REAL, game TEXT, family TEXT) WITHOUT ROWID"
    )
    db.execute(
        "CREATE TABLE IF NOT EXISTS lineage (input BLOB, game TEXT, n INTEGER, first_ply INTEGER, last_ply INTEGER, PRIMARY KEY(input,game)) WITHOUT ROWID"
    )
    counts = {
        "games": 0,
        "completed_games": 0,
        "unfinished_games": 0,
        "raw_positions": 0,
        "within_split_duplicates": 0,
        "feature_equivalent_duplicates": 0,
        "cross_split_conflicts": 0,
        "heldout_samples": 0,
        "heldout_games": 0,
        "teacher_depth_zero_samples": 0,
    }
    hist = {
        key: {}
        for key in [
            "ply",
            "clock",
            "material",
            "phase",
            "outcome",
            "teacher",
            "search_depth",
        ]
    }
    corpus_config = json.loads((a.corpus / "CONFIG.json").read_text())
    preparation_config = {
        "schema": "caissa-prepare-transaction-v1",
        "corpus_config": corpus_config,
        "heldout_inputs": heldout_inputs,
        "dataset_contract": "caissa-dataset-v2",
    }
    db.execute(
        "CREATE TABLE IF NOT EXISTS sources (pair INTEGER PRIMARY KEY, sha256 TEXT NOT NULL)"
    )
    db.execute(
        "CREATE TABLE IF NOT EXISTS transaction_state (key TEXT PRIMARY KEY,value TEXT NOT NULL)"
    )
    previous = db.execute(
        "SELECT value FROM transaction_state WHERE key='config'"
    ).fetchone()
    if previous is not None and json.loads(previous[0]) != preparation_config:
        raise ValueError("preparation source configuration or held-out bytes changed")
    if previous is None:
        db.execute(
            "INSERT INTO transaction_state VALUES(?,?)",
            ("config", json.dumps(preparation_config, sort_keys=True)),
        )
    saved = db.execute(
        "SELECT value FROM transaction_state WHERE key='progress'"
    ).fetchone()
    if saved is not None:
        state = json.loads(saved[0])
        counts = state["counts"]
        hist = state["histograms"]
    split_names = ("train", "validation", "test")
    for split, name in enumerate(split_names):
        if "distinct_" + name + "_inputs" not in counts:
            counts["distinct_" + name + "_inputs"] = db.execute(
                "SELECT count(*) FROM positions WHERE split=?", (split,)
            ).fetchone()[0]
    completed_sources = {
        number: sha for number, sha in db.execute("SELECT pair,sha256 FROM sources")
    }
    start = time.monotonic()
    wall_start = time.time()
    session_pairs = 0

    last_checkpoint_count = -1
    last_checkpoint_time = 0.0

    def checkpoint():
        nonlocal last_checkpoint_count, last_checkpoint_time
        state = {
            "counts": counts,
            "histograms": hist,
            "sources": len(completed_sources),
        }
        db.execute(
            "INSERT INTO transaction_state VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            ("progress", json.dumps(state, sort_keys=True)),
        )
        db.commit()
        atomic_json(
            a.output / "PREPARE_PROGRESS.json",
            {
                "schema": "caissa-preparation-progress-v2",
                "corpus_root": str(a.corpus.resolve()),
                "corpus_config_sha256": digest(a.corpus / "CONFIG.json"),
                "source_pairs": len(completed_sources),
                "counts": counts,
                "seconds_this_session": time.monotonic() - start,
                "wall_seconds_this_session": time.time() - wall_start,
            },
        )
        last_checkpoint_count = len(completed_sources)
        last_checkpoint_time = time.time()
        print(
            json.dumps({"source_pairs": len(completed_sources), **counts}), flush=True
        )

    checkpoint()

    def paths():
        if not a.follow:
            yield from sorted(a.corpus.glob("*/*.json"))
            return
        for number in range(corpus_config["requested_pairs"]):
            path = a.corpus / f"{number//256:06d}" / f"{number:09d}.json"
            while not path.exists():
                if (
                    len(completed_sources) != last_checkpoint_count
                    and time.time() - last_checkpoint_time >= 1
                ):
                    checkpoint()
                with (a.corpus / "CORPUS.lock").open("a") as lock:
                    try:
                        fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    except BlockingIOError:
                        pass
                    else:
                        summary_path = a.corpus / "SUMMARY.json"
                        if summary_path.exists():
                            summary = json.loads(summary_path.read_text())
                            if (
                                summary.get("status") == "completed"
                                and summary.get("completion_mode") == "screened-target"
                                and summary["pairs"] == number
                            ):
                                return
                        raise ValueError(
                            "corpus writer stopped before required pair " + str(number)
                        )
                time.sleep(0.2)
            yield path

    for path in paths():
        number = int(path.stem)
        if number in completed_sources:
            if digest(path) != completed_sources[number]:
                raise ValueError(
                    "completed source pair changed during preparation resume"
                )
            continue
        raw = path.read_bytes()
        pair = json.loads(raw)
        if (
            pair["pair"] != number
            or len(pair["games"]) != 2
            or [game["reverse"] for game in pair["games"]] != [0, 1]
        ):
            raise ValueError("source pair identity differs from journal path")
        if pair.get("schema") != "caissa-selfplay-v1":
            raise ValueError("unsupported corpus journal")
        for g in pair["games"]:
            if (
                g.get("search_policy", "legacy-v1")
                != corpus_config.get("search_policy", "legacy-v1")
                or g["budget_nodes"] != corpus_config["nodes"]
            ):
                raise ValueError(
                    "source game search policy/budget differs from corpus contract"
                )
            counts["games"] += 1
            if not verify_game(g):
                counts["unfinished_games"] += 1
                continue
            counts["completed_games"] += 1
            counts["raw_positions"] += len(g["positions"])
            family = hashlib.sha256(" ".join(g["moves"][:8]).encode()).hexdigest()
            if family in heldout_families:
                counts["heldout_games"] += 1
                continue
            bucket = int(family[:8], 16) % 10
            split = 1 if bucket == 0 else 2 if bucket == 1 else 0
            white = {"1-0": 1.0, "0-1": 0.0, "1/2-1/2": 0.5}[g["result"]]
            game = f"{g['pair']}:{g['reverse']}"
            for s in g["positions"]:
                identity = input_identity(s["fen"])
                position_id = hashlib.sha256(canonical(s["fen"]).encode()).digest()
                if identity in heldout:
                    counts["heldout_samples"] += 1
                    continue
                stm = s["fen"].split()[1]
                outcome = white if stm == "w" else 1 - white
                teacher = float(s["score_stm"])
                if not math.isfinite(teacher) or abs(teacher) > 30000:
                    raise ValueError("invalid original-teacher score")
                probability = 1 / (1 + math.exp(-max(-60.0, min(60.0, teacher / 400))))
                row = db.execute(
                    "SELECT split,position_id FROM positions WHERE input=?", (identity,)
                ).fetchone()
                if row:
                    if row[1] != position_id:
                        counts["feature_equivalent_duplicates"] += 1
                    if row[0] == split:
                        counts["within_split_duplicates"] += 1
                        db.execute(
                            "UPDATE positions SET outcome=outcome+?,teacher_cp=teacher_cp+?,teacher_probability=teacher_probability+?,n=n+1,min_outcome=min(min_outcome,?),max_outcome=max(max_outcome,?) WHERE input=?",
                            (outcome, teacher, probability, outcome, outcome, identity),
                        )
                    elif row[0] != -1:
                        counts["distinct_" + split_names[row[0]] + "_inputs"] -= 1
                        db.execute(
                            "UPDATE positions SET split=-1 WHERE input=?", (identity,)
                        )
                        counts["cross_split_conflicts"] += 1
                else:
                    counts["distinct_" + split_names[split] + "_inputs"] += 1
                    db.execute(
                        "INSERT INTO positions VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                        (
                            identity,
                            position_id,
                            split,
                            s["fen"],
                            outcome,
                            teacher,
                            probability,
                            1,
                            outcome,
                            outcome,
                            game,
                            family,
                        ),
                    )
                db.execute(
                    "INSERT INTO lineage VALUES(?,?,?,?,?) ON CONFLICT(input,game) DO UPDATE SET n=n+1,last_ply=excluded.last_ply",
                    (identity, game, 1, s["ply"], s["ply"]),
                )
                if s["depth"] == 0:
                    counts["teacher_depth_zero_samples"] += 1
                board_part = s["fen"].split()[0]
                phase = min(
                    24,
                    sum(
                        {"n": 1, "b": 1, "r": 2, "q": 4}.get(piece.lower(), 0)
                        for piece in board_part
                    ),
                )
                for key, value in [
                    ("ply", s["ply"] // 10 * 10),
                    ("clock", int(s["fen"].split()[4]) // 10 * 10),
                    ("material", sum(c.isalpha() for c in board_part)),
                    ("phase", phase),
                    ("outcome", outcome),
                    ("teacher", max(-2000, min(2000, int(teacher // 100 * 100)))),
                    ("search_depth", s["depth"]),
                ]:
                    label = str(value)
                    hist[key][label] = hist[key].get(label, 0) + 1
        sha = hashlib.sha256(raw).hexdigest()
        db.execute("INSERT INTO sources VALUES(?,?)", (number, sha))
        completed_sources[number] = sha
        session_pairs += 1
        if session_pairs % 100 == 0:
            checkpoint()
    checkpoint()
    source_pairs = [
        {"pair": number, "sha256": sha}
        for number, sha in db.execute("SELECT pair,sha256 FROM sources ORDER BY pair")
    ]
    source_hash = hashlib.sha256()
    for row in source_pairs:
        source_hash.update(bytes.fromhex(row["sha256"]))
    if a.follow and len(source_pairs) != corpus_config["requested_pairs"]:
        summary = json.loads((a.corpus / "SUMMARY.json").read_text())
        if (
            summary.get("status") != "completed"
            or summary.get("completion_mode") != "screened-target"
            or summary["pairs"] != len(source_pairs)
        ):
            raise ValueError(
                "follow mode did not consume a completed declared acquisition"
            )
        proof = summary["completion_proof"]
        if proof["source_pairs"] != len(source_pairs) or proof["counts"] != counts:
            raise ValueError(
                "screened completion proof differs from actual replayed transaction"
            )
    sizes = {}
    for split, name in [(0, "train"), (1, "validation"), (2, "test")]:
        n = db.execute(
            "SELECT count(*) FROM positions WHERE split=?", (split,)
        ).fetchone()[0]
        sizes[name] = n
        if counts["distinct_" + name + "_inputs"] != n:
            raise ValueError("online distinct split counter differs from actual index")
        if n == 0:
            raise ValueError("empty required split " + name)
        x = np.lib.format.open_memmap(
            a.output / f"{name}-features.npy",
            mode="w+",
            dtype=np.uint16,
            shape=(n, 2, 32),
        )
        y = np.lib.format.open_memmap(
            a.output / f"{name}-targets.npy", mode="w+", dtype=np.float32, shape=(n, 3)
        )
        with (a.output / f"{name}-identities.jsonl").open("w") as ids:
            for i, (
                identity,
                position_id,
                fen,
                outcome,
                teacher,
                probability,
                count,
                game,
                family,
            ) in enumerate(
                db.execute(
                    "SELECT input,position_id,fen,outcome,teacher_cp,teacher_probability,n,game,family FROM positions WHERE split=? ORDER BY input",
                    (split,),
                )
            ):
                x[i] = features(fen)
                y[i] = [outcome / count, teacher / count, probability / count]
                contributors = [
                    {"game": g, "count": c, "first_ply": first, "last_ply": last}
                    for g, c, first, last in db.execute(
                        "SELECT game,n,first_ply,last_ply FROM lineage WHERE input=? ORDER BY game",
                        (identity,),
                    )
                ]
                ids.write(
                    json.dumps(
                        {
                            "input_id": identity.hex(),
                            "position_id": position_id.hex(),
                            "first_game": game,
                            "first_family": family,
                            "observations": count,
                            "contributors": contributors,
                        }
                    )
                    + "\n"
                )
        x.flush()
        y.flush()
        del x, y
    counts["distinct_usable_positions"] = sum(sizes.values())
    counts["quarantined_inputs"] = db.execute(
        "SELECT count(*) FROM positions WHERE split=-1"
    ).fetchone()[0]
    counts["mixed_outcome_inputs"] = db.execute(
        "SELECT count(*) FROM positions WHERE min_outcome<max_outcome AND split>=0"
    ).fetchone()[0]
    atomic_json(a.output / "SOURCE_PAIRS.json", source_pairs)
    manifest = {
        "schema": "caissa-dataset-v2",
        "corpus_config": json.loads((a.corpus / "CONFIG.json").read_text()),
        "corpus_content_sha256": source_hash.hexdigest(),
        "source_pairs_sha256": digest(a.output / "SOURCE_PAIRS.json"),
        "input_identity": "side-to-move normalized placement; rights/EP/clocks excluded; color reflection collapsed",
        "functional_deduplication": True,
        "target_columns": [
            "mean_outcome_stm",
            "mean_original_teacher_cp",
            "mean_original_teacher_win_probability",
        ],
        "ordering": "input SHA256",
        "heldout_inputs": heldout_inputs,
        "counts": counts,
        "splits": sizes,
        "histograms": hist,
        "histogram_scope": "eligible raw observations after held-out family/input screening, before duplicate aggregation",
        "seconds": time.monotonic() - start,
        "parent_cpu_seconds_this_session": time.process_time(),
        "wall_seconds_this_session": time.time() - wall_start,
        "timing_scope": "current preparation session; checkpoint progress preserves work from earlier sessions",
        "files": {p.name: digest(p) for p in a.output.glob("*.npy")},
    }
    atomic_json(a.output / "DATASET.json", manifest)
    db.close()
    print(
        json.dumps(
            {k: v for k, v in manifest.items() if k not in ["histograms", "files"]}
        )
    )


if __name__ == "__main__":
    main()
