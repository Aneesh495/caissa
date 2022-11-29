"""Reconstruct reachable rules probes and replay the exact saved native core.

Expected move sets and perft totals come from an isolated python-chess oracle.
The producer's sampler, parser and result summarizer are never imported.
"""

import argparse
import hashlib
import json
import math
import random
import shutil
import time
from pathlib import Path

import chess

from tools.campaign_process import Campaign, atomic
from verification.bundle import digest_text, strict_json
from verification.source import require
from verification.tactical_generation import Probe


def sha(path):
    result = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1048576), b""):
            result.update(block)
    return result.hexdigest()


def document(path, limit=4 * 1024 * 1024):
    path = Path(path)
    require(
        path.is_file() and not path.is_symlink() and 0 < path.stat().st_size <= limit,
        "rules metadata is missing, linked or excessive",
    )
    raw = path.read_bytes()
    return strict_json(raw), hashlib.sha256(raw).hexdigest()


class Walk:
    def __init__(self, rule):
        self.rule = rule
        self.random = random.Random(rule["seed"])
        self.board = chess.Board()
        self.resets = 0

    def position(self):
        if (
            self.board.is_game_over()
            or self.board.ply() > self.rule["maximum_game_ply"]
            or self.random.random() < self.rule["reset_probability"]
        ):
            self.resets += 1
            if self.resets % self.rule["chess960_every_reset"] == 0:
                self.board = chess.Board.from_chess960_pos(self.random.randrange(960))
            else:
                self.board = chess.Board()
        return self.board

    def advance(self, legal):
        if legal:
            self.board.push_uci(self.random.choice(legal))


def oracle_perft(board, depth, tick, counter, ceiling):
    tick()
    if depth == 0:
        counter[0] += 1
        require(counter[0] <= ceiling, "rules oracle perft node ceiling exhausted")
        return 1
    legal = list(board.legal_moves)
    if depth == 1:
        counter[0] += len(legal)
        require(counter[0] <= ceiling, "rules oracle perft node ceiling exhausted")
        return len(legal)
    nodes = 0
    for move in legal:
        board.push(move)
        try:
            nodes += oracle_perft(board, depth - 1, tick, counter, ceiling)
        finally:
            board.pop()
    return nodes


def verify(
    observations,
    summary_path,
    engine,
    expected_engine,
    profile_path,
    expected_profile,
    fixtures_path,
    expected_observations,
    output,
    *,
    profile="full",
    maximum_seconds=900,
):
    from tools.heuristic_study import avoid_decisive_matches

    avoid_decisive_matches(Path(__file__).resolve().parents[1] / "runs")
    require(profile in {"full", "diagnostic"}, "unsupported rules replay profile")
    rule, identity = document(profile_path)
    require(
        identity == digest_text(expected_profile),
        "rules workload differs from external frozen identity",
    )
    require(
        rule["schema"] == "caissa-rules-replay-v1"
        and rule["status"] == "frozen"
        and rule["positions"] == 100000
        and rule["perft_positions"] == 20
        and rule["seed"] == 1729
        and rule["reset_probability"] == 0.015
        and rule["maximum_game_ply"] == 300
        and rule["chess960_every_reset"] == 4,
        "rules workload, sampler or mandatory sample changed",
    )
    require(
        rule["oracle"] == "chess " + chess.__version__ == "chess 1.11.2",
        "rules oracle version differs",
    )
    require(
        math.isfinite(maximum_seconds)
        and 0 < maximum_seconds <= rule["maximum_seconds"] == 900,
        "rules replay deadline exceeds frozen ceiling",
    )
    summary, _ = document(summary_path)
    requested = summary["requested"]
    require(
        type(requested) is int and 1 <= requested <= rule["positions"],
        "rules requested count is invalid",
    )
    require(
        profile != "full" or requested == rule["positions"],
        "full rules replay needs all100000 positions",
    )
    require(
        type(summary["completed"]) is int and type(summary["unique"]) is int,
        "rules completion counts must be integers",
    )
    require(
        summary["seed"] == rule["seed"] and summary["oracle"] == rule["oracle"],
        "rules raw sampler or oracle differs",
    )
    engine = Path(engine)
    require(
        engine.is_file()
        and not engine.is_symlink()
        and 0 < engine.stat().st_size <= 32 * 1024 * 1024,
        "rules saved executable is missing, linked or excessive",
    )
    require(
        summary["engine_sha256"] == digest_text(expected_engine) == sha(engine),
        "rules saved-engine identity differs",
    )
    require(
        summary["observations_sha256"] == digest_text(expected_observations),
        "rules raw observations differ from the external pin",
    )
    fixtures, fixture_sha = document(fixtures_path)
    require(
        fixture_sha == rule["perft_sha256"]
        and len(fixtures["positions"]) == 20
        and len({row["id"] for row in fixtures["positions"]}) == 20,
        "rules frozen perft inventory differs",
    )
    observations, output = Path(observations), Path(output)
    require(
        observations.is_file()
        and not observations.is_symlink()
        and observations.stat().st_size
        <= rule["maximum_observation_bytes"]
        == 512 * 1024 * 1024,
        "rules observation file is missing, linked or excessive",
    )
    require(
        not output.resolve().is_relative_to(observations.parent.resolve()),
        "rules replay cannot mutate original evidence",
    )
    deadline = time.time() + maximum_seconds
    campaign = Campaign(
        output,
        {
            "profile": profile,
            "gate": "G01",
            "engine_sha256": expected_engine,
            "profile_sha256": identity,
            "observations_sha256": expected_observations,
            "requested": requested,
            "maximum_seconds": maximum_seconds,
            "full_acceptance": False,
        },
        maximum_seconds,
        absolute_deadline=deadline,
    )
    copied = output / "bin/caissa"
    probe = None
    completed, byte_count = 0, 0
    seen = set()
    content_hash = hashlib.sha256()

    def tick():
        require(
            time.monotonic() < campaign.deadline and time.time() < deadline,
            "cumulative rules replay deadline exhausted",
        )

    try:
        copied.parent.mkdir()
        shutil.copy2(engine, copied)
        copied.chmod(0o755)
        require(sha(copied) == expected_engine, "copied rules executable bytes differ")
        probe = Probe(copied, "--inspect", deadline)
        walk = Walk(rule)
        with (
            observations.open("rb") as stream,
            (output / "native-observations.jsonl").open("x") as replay,
        ):
            while True:
                tick()
                raw = stream.readline(16385)
                if not raw:
                    break
                byte_count += len(raw)
                require(
                    len(raw) <= 16384
                    and raw.endswith(b"\n")
                    and byte_count <= rule["maximum_observation_bytes"],
                    "rules raw line is oversized, partial or over budget",
                )
                require(
                    completed < requested,
                    "rules observations exceed the frozen requested work",
                )
                content_hash.update(raw)
                row = strict_json(raw)
                board = walk.position()
                fen = board.fen(en_passant="fen")
                require(
                    type(row["i"]) is int
                    and row["i"] == completed
                    and type(row["chess960"]) is bool
                    and row["chess960"] == board.chess960
                    and row["fen"] == fen,
                    "rules observation is not the frozen reachable walk",
                )
                legal = sorted(board.uci(move) for move in board.legal_moves)
                require(
                    row["expected"] == legal
                    and row["actual"] == legal
                    and type(row["check_expected"]) is bool
                    and row["check_expected"] == board.is_check()
                    and type(row["check_actual"]) is bool
                    and row["check_actual"] == board.is_check(),
                    "rules saved move/check results disagree with independent oracle",
                )
                native = probe.request(("960|" if board.chess960 else "") + fen)
                require(
                    "error" not in native
                    and sorted(native.get("moves", [])) == legal
                    and type(native.get("check")) is bool
                    and native["check"] == board.is_check(),
                    "saved native rules replay disagrees with independent oracle",
                )
                parsed = chess.Board(native["fen"], chess960=board.chess960)
                require(
                    parsed.fen(en_passant="fen") == fen,
                    "saved native FEN changed game semantics",
                )
                replay.write(
                    json.dumps(
                        {
                            "i": completed,
                            "fen": fen,
                            "chess960": board.chess960,
                            "native": native,
                            "oracle_moves": legal,
                        },
                        separators=(",", ":"),
                    )
                    + "\n"
                )
                require(
                    replay.tell() <= rule["maximum_observation_bytes"],
                    "rules replay output byte ceiling",
                )
                seen.add(
                    (
                        board.chess960,
                        board.board_fen(),
                        board.turn,
                        board.castling_rights,
                        board.ep_square if board.has_legal_en_passant() else None,
                    )
                )
                completed += 1
                walk.advance(legal)
                if completed % 1000 == 0:
                    replay.flush()
                    atomic(
                        output / "PROGRESS.json",
                        {
                            "phase": "reachable-position-replay",
                            "completed": completed,
                            "requested": requested,
                            "unique": len(seen),
                            "full_acceptance": False,
                        },
                    )
        require(
            completed == requested == summary["completed"]
            and len(seen) == summary["unique"],
            "rules useful-work or distinct-position counts disagree",
        )
        require(
            content_hash.hexdigest() == expected_observations,
            "rules observations changed during semantic replay",
        )
        probe.close()
        require(
            probe.process.returncode == 0,
            "rules native process failed or needed forced cleanup",
        )
        probe = None
        counter, perft = [0], []
        for row in fixtures["positions"]:
            require(
                type(row["depth"]) is int
                and 1 <= row["depth"] <= 4
                and type(row["chess960"]) is bool
                and type(row["nodes"]) is int
                and row["nodes"] > 0,
                "rules perft fixture has unsupported depth, variant or total",
            )
            board = chess.Board(row["fen"], chess960=row["chess960"])
            reference = oracle_perft(
                board, row["depth"], tick, counter, rule["maximum_oracle_perft_nodes"]
            )
            require(
                reference == row["nodes"],
                "known perft total disagrees with independent oracle",
            )
            stage = "perft-" + row["id"]
            command = [
                str(copied.resolve()),
                "--perft",
                str(row["depth"]),
                row["fen"],
            ] + (["960"] if row["chess960"] else [])
            campaign.run(stage, command, 60, maximum_output_bytes=1024)
            native = int((output / (stage + ".log")).read_text())
            require(
                native == reference,
                "saved native perft total differs from independent oracle",
            )
            perft.append(
                {
                    "id": row["id"],
                    "depth": row["depth"],
                    "native": native,
                    "oracle": reference,
                }
            )
        require(
            sha(copied) == expected_engine,
            "saved rules executable changed during replay",
        )
        result = {
            "status": "passed",
            "gate": "G01",
            "profile": profile,
            "full_gate": profile == "full" and completed == 100000 and len(perft) == 20,
            "full_acceptance": False,
            "positions": completed,
            "unique": len(seen),
            "perft": perft,
            "engine_sha256": expected_engine,
            "profile_sha256": identity,
            "observations_sha256": expected_observations,
            "scope": "Exact saved-core rules replay and independent reachable-walk/perft oracle; other full gates remain separate",
        }
        atomic(output / "RULES.json", result)
        campaign.close(
            (
                "passed G01 semantic replay"
                if result["full_gate"]
                else "passed diagnostic rules prefix"
            ),
            result,
        )
        return result
    except BaseException as error:
        if probe is not None:
            try:
                probe.close()
            except OSError as cleanup:
                atomic(
                    output / "CLEANUP_FAILURE.json",
                    {"error": repr(cleanup), "primary": repr(error)},
                )
        campaign.close(
            "failed",
            {
                "error": repr(error),
                "completed_positions": completed,
                "full_acceptance": False,
            },
        )
        raise


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--observations", type=Path, required=True)
    parser.add_argument("--summary", type=Path, required=True)
    parser.add_argument("--engine", type=Path, required=True)
    parser.add_argument("--expected-engine-sha256", required=True)
    parser.add_argument("--protocol", type=Path, required=True)
    parser.add_argument("--expected-protocol-sha256", required=True)
    parser.add_argument("--fixtures", type=Path, required=True)
    parser.add_argument("--expected-observations-sha256", required=True)
    parser.add_argument("--profile", choices=["full", "diagnostic"], default="full")
    parser.add_argument("--maximum-seconds", type=float, default=900)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        from tools.heuristic_study import avoid_decisive_matches

        avoid_decisive_matches()
        result = verify(
            args.observations,
            args.summary,
            args.engine,
            args.expected_engine_sha256,
            args.protocol,
            args.expected_protocol_sha256,
            args.fixtures,
            args.expected_observations_sha256,
            args.output,
            profile=args.profile,
            maximum_seconds=args.maximum_seconds,
        )
        print(json.dumps(result))
        return 0
    except (
        ValueError,
        TypeError,
        IndexError,
        KeyError,
        OSError,
        RuntimeError,
    ) as error:
        print(
            json.dumps(
                {"status": "rejected", "reason": str(error), "full_acceptance": False}
            )
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
