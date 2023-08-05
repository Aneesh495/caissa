"""Rebuild the committed SQL generation and final splits without the preparer."""

import argparse
import contextlib
import hashlib
import json
import math
import re
import shutil
import sqlite3
import tempfile
import time
from pathlib import Path

from verification.bundle import Bundle
from verification.dataset import holdouts, normalized, original_game, verify_dataset
from verification.source import require

CORPUS = "818eb731b568d5b7526f20f8b374e516e28b4dd5e48431333ddffdab68ce493e"
DATASET = "51ab630fd7c986efa3010d0f2fc8b6bc1108af0917dc4ec408253a9de21be20e"
PAIRS = "b56c15c47d789e3a1d0a07329b2e6eaa9f89e4d3fe3b040b63de7e59cb8f63d4"
EXPORTS = {
    "DATASET.json",
    "SOURCE_PAIRS.json",
    *{
        f"{s}-{k}"
        for s in ["train", "validation", "test"]
        for k in ["features.npy", "targets.npy", "identities.jsonl"]
    },
}


def admit(config, source):
    expected = {
        "schema": "caissa-data-recovery-v1",
        "profile": "data-recovery-component-only",
        "source_commit": source,
        "corpus_config_sha256": CORPUS,
        "original_dataset_sha256": DATASET,
        "original_source_pairs_sha256": PAIRS,
        "pairs": 56,
        "committed_sources": 32,
        "uncommitted_sources": 52,
        "maximum_seconds": 120,
        "maximum_output_bytes": 1024**3,
        "minimum_free_bytes": 10 * 1024**3,
        "full_G11_certified": False,
    }
    require(
        isinstance(config, dict)
        and set(config) == set(expected) | {"started_unix", "deadline_unix"},
        "data recovery scope inventory differs",
    )
    require(
        re.fullmatch(r"[0-9a-f]{40}", source or ""),
        "data recovery source identity missing",
    )
    require(
        all(type(config[k]) is type(v) and config[k] == v for k, v in expected.items()),
        "data recovery source or original scope differs",
    )
    require(
        type(config["started_unix"]) is float
        and math.isfinite(config["started_unix"])
        and type(config["deadline_unix"]) is float
        and config["deadline_unix"] == config["started_unix"] + 120,
        "data recovery cumulative deadline differs",
    )


def prefix_rows(root, heldout, excluded):
    """Build independent position and contributor maps for the 32 durable pairs."""
    positions, lineage = {}, {}
    raw_count = complete = 0
    for number in range(32):
        pair = json.loads((root / "corpus/000000" / f"{number:09d}.json").read_bytes())
        for game in pair["games"]:
            observations = original_game(game)
            if not game["complete"]:
                continue
            complete += 1
            raw_count += len(observations)
            family = hashlib.sha256(" ".join(game["moves"][:8]).encode()).hexdigest()
            if family in excluded:
                continue
            bucket = int(family[:8], 16) % 10
            split = 1 if bucket == 0 else 2 if bucket == 1 else 0
            white = {"1-0": 1.0, "0-1": 0.0, "1/2-1/2": 0.5}[game["result"]]
            name = f"{game['pair']}:{game['reverse']}"
            for board, sample in observations:
                identity, _ = normalized(board)
                if identity in heldout:
                    continue
                fen = sample["fen"]
                position_id = hashlib.sha256(
                    " ".join(board.fen(en_passant="legal").split()[:4]).encode()
                ).digest()
                outcome = white if board.turn else 1 - white
                teacher = float(sample["score_stm"])
                probability = 1 / (1 + math.exp(-max(-60, min(60, teacher / 400))))
                row = positions.get(identity)
                if row is None:
                    positions[identity] = [
                        identity,
                        position_id,
                        split,
                        fen,
                        outcome,
                        teacher,
                        probability,
                        1,
                        outcome,
                        outcome,
                        name,
                        family,
                    ]
                elif row[2] == split:
                    row[4] += outcome
                    row[5] += teacher
                    row[6] += probability
                    row[7] += 1
                    row[8] = min(row[8], outcome)
                    row[9] = max(row[9], outcome)
                elif row[2] != -1:
                    row[2] = -1
                key = identity, name
                if key not in lineage:
                    lineage[key] = [identity, name, 0, sample["ply"], sample["ply"]]
                lineage[key][2] += 1
                lineage[key][4] = sample["ply"]
    return (
        [positions[k] for k in sorted(positions)],
        [lineage[k] for k in sorted(lineage)],
        complete,
        raw_count,
    )


def verify(root, source, maximum_seconds=60):
    from tools.heuristic_study import avoid_decisive_matches
    from tools.host_lease import HostLease, inherited

    avoid_decisive_matches()
    root = Path(root).resolve()
    started = time.monotonic()
    with contextlib.ExitStack() as cleanup:
        if not inherited(Path.cwd() / "runs/TIMED_STRENGTH.lock"):
            lease = HostLease(Path.cwd() / "runs")
            cleanup.callback(lease.close)
        bundle = cleanup.enter_context(Bundle(root, maximum_seconds))
        bundle.verify_manifest()
        config = bundle.json("CONFIG.json")
        admit(config, source)
        expected = {
            "CONFIG.json",
            "KILL.json",
            "ORIGINAL_DATASET.json",
            "ORIGINAL_SOURCE_PAIRS.json",
            "config/studies.json",
            "config/strength-openings.json",
            "corpus/CONFIG.json",
            *{f"corpus/000000/{i:09d}.json" for i in range(56)},
            *{
                f"boundary/{n}"
                for n in [
                    "RECOVERY_READY.json",
                    "PREPARE_PROGRESS.json",
                    "identities.sqlite3",
                    "identities.sqlite3-wal",
                    "identities.sqlite3-shm",
                ]
            },
            *{f"{folder}/{n}" for folder in ["whole", "recovered"] for n in EXPORTS},
        }
        require(
            set(bundle.identities) == expected, "data recovery raw inventory differs"
        )
        for name in expected:
            bundle.bytes(name, 16 * 1024**2)
        for name, digest in [
            ("ORIGINAL_DATASET.json", DATASET),
            ("ORIGINAL_SOURCE_PAIRS.json", PAIRS),
            ("corpus/CONFIG.json", CORPUS),
        ]:
            require(
                hashlib.sha256(bundle.bytes(name)).hexdigest() == digest,
                "original published data identity differs",
            )
        entries = bundle.json("ORIGINAL_SOURCE_PAIRS.json")
        require(
            [e["pair"] for e in entries] == list(range(56)),
            "original pair inventory differs",
        )
        for entry in entries:
            require(
                hashlib.sha256(
                    bundle.bytes(f"corpus/000000/{entry['pair']:09d}.json")
                ).hexdigest()
                == entry["sha256"],
                "original game pair bytes differ",
            )
        kill, ready, progress = (
            bundle.json(n)
            for n in [
                "KILL.json",
                "boundary/RECOVERY_READY.json",
                "boundary/PREPARE_PROGRESS.json",
            ]
        )
        require(
            type(kill["signal"]) is int
            and kill["signal"] == 9
            and type(kill["actual_exit"]) is int
            and kill["actual_exit"] == -9
            and type(kill["pid"]) is int
            and kill["pid"] > 1
            and type(kill["signal_sent_ns"]) is int
            and type(kill["reaped_ns"]) is int
            and kill["signal_sent_ns"] < kill["reaped_ns"],
            "data recovery lacks an actual forced SIGKILL",
        )
        require(
            ready
            == {
                "schema": "caissa-data-recovery-boundary-v1",
                "committed_sources": 32,
                "uncommitted_sources": 52,
                "pid": kill["pid"],
            }
            and type(ready["committed_sources"]) is int
            and type(ready["uncommitted_sources"]) is int
            and progress["source_pairs"] == 32,
            "committed/uncommitted data boundary differs",
        )
        reference = bundle.json("ORIGINAL_DATASET.json")
        whole, recovered = bundle.json("whole/DATASET.json"), bundle.json(
            "recovered/DATASET.json"
        )
        for key in [
            "schema",
            "corpus_config",
            "corpus_content_sha256",
            "source_pairs_sha256",
            "files",
            "splits",
            "counts",
            "histograms",
            "heldout_inputs",
            "functional_deduplication",
            "ordering",
            "target_columns",
        ]:
            require(
                whole[key] == recovered[key] == reference[key],
                "data recovery export metadata differs: " + key,
            )
        for name in EXPORTS - {"DATASET.json"}:
            require(
                bundle.bytes("whole/" + name) == bundle.bytes("recovered/" + name),
                "uninterrupted/resumed exported bytes differ",
            )
        with tempfile.TemporaryDirectory(
            prefix="caissa-data-recovery-reader-"
        ) as temporary:
            temporary = Path(temporary)
            for name in expected:
                destination = temporary / name
                destination.parent.mkdir(parents=True, exist_ok=True)
                bundle.copy(name, destination, 16 * 1024**2)
            with contextlib.chdir(temporary):
                heldout, excluded = holdouts(
                    Path("config/studies.json"), Path("config/strength-openings.json")
                )
                rows, contributors, completed, raw = prefix_rows(
                    temporary, heldout, excluded
                )
                with contextlib.closing(
                    sqlite3.connect(
                        f"file:{temporary / 'boundary/identities.sqlite3'}?mode=ro",
                        uri=True,
                    )
                ) as connection:
                    require(
                        connection.execute("PRAGMA integrity_check").fetchone()[0]
                        == "ok",
                        "committed SQLite generation is malformed",
                    )
                    sources = connection.execute(
                        "SELECT pair,sha256 FROM sources ORDER BY pair"
                    ).fetchall()
                    require(
                        sources == [(e["pair"], e["sha256"]) for e in entries[:32]],
                        "committed SQL sources differ from original prefix",
                    )
                    actual = connection.execute(
                        "SELECT * FROM positions ORDER BY input"
                    ).fetchall()
                    require(
                        len(actual) == len(rows), "committed SQL position count differs"
                    )
                    for left, right in zip(actual, rows):
                        require(
                            all(
                                (
                                    math.isclose(a, b, rel_tol=1e-12, abs_tol=1e-10)
                                    if type(a) is float and type(b) is float
                                    else type(a) is type(b) and a == b
                                )
                                for a, b in zip(left, right)
                            ),
                            "committed SQL positions differ from original games",
                        )
                    require(
                        connection.execute(
                            "SELECT * FROM lineage ORDER BY input,game"
                        ).fetchall()
                        == [tuple(row) for row in contributors],
                        "committed SQL contributor lineage differs",
                    )
                    state = json.loads(
                        connection.execute(
                            "SELECT value FROM transaction_state WHERE key='progress'"
                        ).fetchone()[0]
                    )
                    require(
                        state["sources"] == 32
                        and state["counts"] == progress["counts"]
                        and state["counts"]["games"] == 64
                        and state["counts"]["completed_games"] == completed
                        and state["counts"]["raw_positions"] == raw,
                        "committed progress and SQL generation differ",
                    )
                bundle.tick()
                result = verify_dataset(
                    temporary / "recovered",
                    temporary / "corpus",
                    Path("config/studies.json"),
                    Path("config/strength-openings.json"),
                    maximum_seconds=max(
                        1, maximum_seconds - (time.monotonic() - started)
                    ),
                    scratch=temporary / "oracle",
                )
                require(
                    result["source_pairs"] == 56
                    and result["independently_rebuilt_splits"] == reference["splits"],
                    "recovered complete split replay differs",
                )
        return {
            "status": "passed",
            "component": "original-data-recovery",
            "component_pass": True,
            "committed_sources": 32,
            "uncommitted_sources_at_kill": 52,
            "recovered_sources": 56,
            "committed_positions_independently_rebuilt": len(rows),
            "committed_contributors_independently_rebuilt": len(contributors),
            "final_splits": result["independently_rebuilt_splits"],
            "exact_export_parity": True,
            "original_labels_unchanged": True,
            "full_G11_certified": False,
            "final_source_and_native_binding_required": True,
        }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("evidence", type=Path)
    parser.add_argument("--source-commit", required=True)
    args = parser.parse_args()
    try:
        print(json.dumps(verify(args.evidence, args.source_commit)))
    except (ValueError, KeyError, OSError, TypeError, sqlite3.Error) as error:
        print(
            json.dumps(
                {
                    "status": "rejected",
                    "reason": str(error),
                    "full_G11_certified": False,
                }
            )
        )
        raise SystemExit(1)


if __name__ == "__main__":
    main()
