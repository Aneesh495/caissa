"""Reconstruct real browser board, PGN, network and native-search observations.

This component keeps final-source product acceptance separate. Screenshots and
saved success flags alone cannot establish legal edits or native analysis.
"""

import argparse
import hashlib
import io
import json
import math
import struct
import zipfile
from pathlib import Path

import chess
import chess.pgn

from verification.bundle import Bundle, strict_json
from verification.source import relative_path, require

STEPS = [
    "fresh",
    "import",
    "keyboard-edit",
    "export",
    "flip",
    "analysis",
    "cancel",
    "cancel-reaped",
    "position-change",
    "navigation-reaped",
    "malformed-fen",
    "stale-session",
    "restored",
    "final-export",
]
START = chess.STARTING_FEN
SELECTED = "52d0306143392ad683c3ebb09fe013f34e1f9e2bc44d3aa153b32314207374b7"


def admit(config, engine_sha256, network_sha256, source_commit):
    require(
        config.get("schema") == "caissa-browser-campaign-v1"
        and config.get("profile") == "browser-component-only"
        and config.get("source_commit") == source_commit
        and config.get("engine_sha256") == engine_sha256
        and config.get("network_sha256") == network_sha256 == SELECTED,
        "G12 browser source, program or selected network differs",
    )
    require(
        config.get("viewports") == [1280, 390]
        and config.get("modes") == ["classical", "neural"]
        and type(config.get("neural_weight")) is int
        and config["neural_weight"] == 10
        and type(config.get("classical_contract")) is int
        and config["classical_contract"] == 1
        and config.get("lazy_neural") is True
        and config.get("playwright") == "1.56.1"
        and config.get("full_G12_certified") is False,
        "G12 browser changed its actual evaluator or component scope",
    )
    start, deadline = config.get("started_unix"), config.get("deadline_unix")
    require(
        all(type(v) in (int, float) and math.isfinite(v) for v in [start, deadline])
        and config.get("maximum_seconds") == 240
        and deadline - start == 240
        and config.get("maximum_additional_bytes") == 256 * 1024**2
        and config.get("minimum_free_bytes") == 10 * 1024**3,
        "G12 browser original finite bounds differ",
    )


def tree(text):
    require(isinstance(text, str) and len(text) < 1048576, "G12 PGN exceeds bounds")
    stream = io.StringIO(text)
    game = chess.pgn.read_game(stream)
    require(
        game is not None and not game.errors and chess.pgn.read_game(stream) is None,
        "G12 PGN is malformed",
    )
    paths = set()

    def walk(node, prefix=()):
        require(len(prefix) <= 512 and len(paths) < 2000, "G12 PGN tree exceeds bounds")
        for child in node.variations:
            board = node.board()
            require(
                child.move in board.legal_moves, "G12 exported PGN has illegal move"
            )
            path = prefix + (child.move.uci(),)
            paths.add(path)
            walk(child, path)

    walk(game)
    return game, paths


def cells(row, fen):
    board = chess.Board(fen)
    actual = row["cells"]
    require(
        len(actual) == 64 and len({x["square"] for x in actual}) == 64,
        "G12 board is missing squares",
    )
    require(
        sum(x["tab"] == 0 for x in actual) == 1
        and all(type(x["tab"]) is int and x["tab"] in [-1, 0] for x in actual),
        "G12 keyboard focus order is invalid",
    )
    order = [
        chess.square_name(chess.square(f, r))
        for r in range(7, -1, -1)
        for f in range(8)
    ]
    require(
        [x["square"] for x in actual]
        == (list(reversed(order)) if row["name"] == "flip" else order),
        "G12 board orientation is invalid",
    )
    for square in actual:
        piece = board.piece_at(chess.parse_square(square["square"]))
        label = square["square"] + (
            " empty"
            if piece is None
            else " "
            + ("white " if piece.color else "black ")
            + chess.piece_name(piece.piece_type)
        )
        require(
            square["label"] == label, "G12 rendered board differs from actual position"
        )


def frames(raw):
    result = []
    for frame in raw.strip().split("\n\n"):
        lines = frame.splitlines()
        require(
            len(lines) == 2
            and lines[0].startswith("event: ")
            and lines[1].startswith("data: "),
            "G12 malformed native stream",
        )
        result.append((lines[0][7:], strict_json(lines[1][6:])))
    return result


def verify(root, engine_sha256, network_sha256, source_commit, maximum_seconds=60):
    with Bundle(root, maximum_seconds) as bundle:
        bundle.verify_manifest()
        config = bundle.json("CONFIG.json")
        admit(config, engine_sha256, network_sha256, source_commit)
        document = bundle.json("BROWSER.json")
        network = bundle.json("NETWORK.json", 32 * 1024**2)
        require(
            document.get("schema") == "caissa-browser-observations-v1"
            and document.get("errors") == []
            and bundle.json("ERRORS.json") == [],
            "G12 browser reported an execution error",
        )
        require(
            type(document.get("elapsed_ms")) is int
            and 0 < document["elapsed_ms"] < 240000,
            "G12 browser duration exceeds original ceiling",
        )
        rows = document["records"]
        require(
            len(rows) == 4 * len(STEPS)
            and isinstance(network, list)
            and len(network) <= 1000,
            "G12 browser sample is missing or excessive",
        )
        expected_names = {
            "CONFIG.json",
            "BROWSER.json",
            "NETWORK.json",
            "ERRORS.json",
            "service.log",
            "WRITER.lock",
            "COMMANDS.jsonl",
            "browser.log",
            "browser.json",
            "CAMPAIGN.json",
            *{
                f"{mode}-{width}/{name}.png"
                for mode in ["classical", "neural"]
                for width in [1280, 390]
                for name in ["import", "keyboard-edit", "analysis", "restored"]
            },
            *{
                f"{mode}-{width}/trace.zip"
                for mode in ["classical", "neural"]
                for width in [1280, 390]
            },
        }
        require(
            set(bundle.identities) == expected_names,
            "G12 raw browser inventory differs",
        )
        require(
            bundle.json("browser.json")["exit"] == 0
            and bundle.json("CAMPAIGN.json")["status"] == "recorded",
            "G12 real browser command did not finish",
        )
        edited = chess.Board()
        edited.push_uci("c2c4")
        edited_fen = edited.fen(en_passant="fen")
        expected_paths = {
            ("e2e4",),
            ("e2e4", "e7e5"),
            ("e2e4", "e7e5", "g1f3"),
            ("d2d4",),
            ("d2d4", "d7d5"),
            ("c2c4",),
        }
        native_lines = 0
        for mode in ["classical", "neural"]:
            for width in [1280, 390]:
                observed = [
                    r for r in rows if r["mode"] == mode and r["width"] == width
                ]
                require(
                    [r["name"] for r in observed] == STEPS,
                    "G12 browser action sequence differs",
                )
                by_name = {r["name"]: r for r in observed}
                for row in observed:
                    bundle.tick()
                    if row["name"] in ["cancel-reaped", "navigation-reaped"]:
                        require(
                            row["health"] == {"positions": 0, "analyses": 0},
                            "G12 native cancellation did not reap workers",
                        )
                        continue
                    if row["name"] == "stale-session":
                        require(
                            type(row["status"]) is int
                            and row["status"] == 403
                            and "token" in strict_json(row["body"])["error"],
                            "G12 restart accepted stale session",
                        )
                        continue
                    require(
                        type(row["scrollWidth"]) is int
                        and row["scrollWidth"] <= width == row["innerWidth"],
                        "G12 constrained viewport overflowed",
                    )
                    expected_fen = (
                        START
                        if row["name"]
                        in ["fresh", "import", "position-change", "malformed-fen"]
                        else edited_fen
                    )
                    if row["name"] != "malformed-fen":
                        require(
                            row["fen"] == expected_fen,
                            "G12 actual edited or restored FEN differs",
                        )
                    else:
                        require(
                            row["error"] is True and "Invalid" in row["status"],
                            "G12 malformed FEN did not show an error",
                        )
                    cells(row, expected_fen)
                    require(
                        row["engine"]
                        == "Caissa · "
                        + (
                            "classical"
                            if mode == "classical"
                            else "experimental neural blend (10%)"
                        )
                        + " evaluation",
                        "G12 rendered evaluator identity differs",
                    )
                require(
                    by_name["keyboard-edit"]["focus"] == "c4",
                    "G12 keyboard destination lost focus",
                )
                require(
                    by_name["position-change"]["lines"] == []
                    and by_name["position-change"]["nodes"] == "0"
                    and by_name["position-change"]["depth"] == "0 / 0"
                    and by_name["position-change"]["nps"] == "0",
                    "G12 stale analysis leaked into another position",
                )
                require(
                    type(by_name["cancel"]["elapsed_ms"]) is int
                    and 0 <= by_name["cancel"]["elapsed_ms"] < 1500,
                    "G12 cancellation exceeded UI deadline",
                )
                for name in ["export", "final-export"]:
                    game, paths = tree(by_name[name]["pgn"])
                    require(
                        paths == expected_paths
                        and game.variations[0].move.uci() == "c2c4",
                        "G12 export lost or changed the edited variation",
                    )
                saved = strict_json(by_name["restored"]["storage"])
                require(
                    saved["version"] == 2
                    and saved["path"] == ["c2c4"]
                    and tree(saved["pgn"])[1] == expected_paths,
                    "G12 persistence lost actual tree or selection",
                )
                selected_requests = [
                    r for r in network if r["mode"] == mode and r["width"] == width
                ]
                sessions = [
                    strict_json(r["body"])
                    for r in selected_requests
                    if r["url"] == "/api/session" and "body" in r
                ]
                require(
                    len({s["token"] for s in sessions}) >= 2
                    and all(
                        s["networkSha256"]
                        == (network_sha256 if mode == "neural" else None)
                        for s in sessions
                    ),
                    "G12 restarted service or network identity differs",
                )
                complete = [
                    r
                    for r in selected_requests
                    if r["url"] == "/api/analyze"
                    and r["status"] == 200
                    and "body" in r
                    and "event: bestmove" in r["body"]
                ]
                require(
                    complete, "G12 browser lacks completed original native analysis"
                )
                saw_neural = False
                for request in complete:
                    parameters = strict_json(request["request"])
                    board = chess.Board(
                        parameters["fen"], chess960=parameters["chess960"]
                    )
                    for uci in parameters["moves"]:
                        move = chess.Move.from_uci(uci)
                        require(
                            move in board.legal_moves,
                            "G12 browser submitted illegal history",
                        )
                        board.push(move)
                    stream = frames(request["body"])
                    require(
                        stream[0][0] == "started"
                        and not any(k == "error" for k, _ in stream),
                        "G12 native search failed",
                    )
                    require(
                        stream[0][1]["networkSha256"]
                        == (network_sha256 if mode == "neural" else None),
                        "G12 native stream changed evaluator identity",
                    )
                    for event, value in stream:
                        if event == "info":
                            position = board.copy()
                            for uci in value.get("pv", []):
                                move = chess.Move.from_uci(uci)
                                require(
                                    move in position.legal_moves,
                                    "G12 native principal variation is illegal",
                                )
                                position.push(move)
                            native_lines += 1
                        elif event == "bestmove":
                            require(
                                chess.Move.from_uci(value["move"]) in board.legal_moves,
                                "G12 native best move is illegal",
                            )
                        elif event == "statistics":
                            require(
                                (
                                    value["neural_evaluations"] == 0
                                    if mode == "classical"
                                    else value["neural_evaluations"] > 0
                                ),
                                "G12 requested evaluator was not actually used",
                            )
                            saw_neural = True
                require(
                    saw_neural,
                    "G12 completed browser search lacks actual evaluator counters",
                )
                image_prefix = f"{mode}-{width}/"
                for name in ["import", "keyboard-edit", "analysis", "restored"]:
                    png = bundle.bytes(image_prefix + name + ".png", 16 * 1024**2)
                    require(
                        png[:8] == b"\x89PNG\r\n\x1a\n"
                        and struct.unpack(">II", png[16:24])[0] == width,
                        "G12 actual screenshot viewport differs",
                    )
                raw = bundle.bytes(image_prefix + "trace.zip", 64 * 1024**2)
                with zipfile.ZipFile(io.BytesIO(raw)) as archive:
                    entries = archive.infolist()
                    require(
                        len(entries) <= 10000
                        and sum(e.file_size for e in entries) <= 128 * 1024**2
                        and len({e.filename for e in entries}) == len(entries),
                        "G12 trace archive exceeds bounds or duplicates names",
                    )
                    for entry in entries:
                        relative_path(entry.filename)
                    require(
                        any(e.filename.endswith(".trace") for e in entries)
                        and any(e.filename.endswith(".network") for e in entries),
                        "G12 actual browser trace or network capture is missing",
                    )
        return {
            "status": "passed",
            "component_pass": True,
            "contexts": 4,
            "reconstructed_board_states": 44,
            "native_lines": native_lines,
            "full_G12_certified": False,
            "final_source_reexecution_required": True,
        }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("evidence", type=Path)
    parser.add_argument("--engine-sha256", required=True)
    parser.add_argument("--network-sha256", required=True)
    parser.add_argument("--source-commit", required=True)
    args = parser.parse_args()
    try:
        result = verify(
            args.evidence, args.engine_sha256, args.network_sha256, args.source_commit
        )
    except (
        ValueError,
        KeyError,
        TypeError,
        OSError,
        AssertionError,
        zipfile.BadZipFile,
    ) as error:
        print(
            json.dumps(
                {"status": "rejected", "reason": str(error), "component_pass": False}
            )
        )
        return 1
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
