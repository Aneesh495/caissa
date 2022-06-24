"""Compare optimized blends with the frozen old evaluator and search."""

import argparse
import hashlib
import json
import random
import struct
import subprocess
import tempfile
import zlib
from pathlib import Path

import chess
from arena.client import UciClient
from verification.classical import evaluate

parser = argparse.ArgumentParser()
parser.add_argument("--engine", default="build-weighted/caissa")
parser.add_argument("--previous", default="data/searched-teacher-v3/caissa")
parser.add_argument("--network", default="runs/residual-prefix-selected/selected.cai")
parser.add_argument("--output", type=Path, required=True)
a = parser.parse_args()
a.output.mkdir(parents=True, exist_ok=False)
rng = random.Random(32452843)
board = chess.Board()
fens = []
for _ in range(256):
    if board.is_game_over() or board.ply() > 160:
        board = chess.Board()
    fens.append(board.fen(en_passant="fen"))
    board.push(rng.choice(list(board.legal_moves)))
text = "\n".join(fens) + "\n"
(a.output / "positions.fen").write_text(text)


def probes(engine, network, weight=None, positions=text):
    command = [engine, "--net-probe", str(network)]
    if weight is not None:
        command.append(str(weight))
    execution = subprocess.run(
        command, input=positions, capture_output=True, text=True, timeout=60, check=True
    )
    rows = [json.loads(line) for line in execution.stdout.splitlines()]
    assert len(rows) == len(positions.splitlines())
    assert all(row["native"] == row["scalar"] for row in rows)
    return [row["native"] for row in rows]


checked = 0
with tempfile.TemporaryDirectory(prefix="blend-extremes-", dir=a.output) as temp:
    variants = [Path(a.network)]
    raw = bytearray(Path(a.network).read_bytes())
    assert raw[:8] == b"CAISSAN3"
    for sign in [-1, 1]:
        altered = bytearray(raw)
        struct.pack_into("<i", altered, len(altered) - 4, sign * (1 << 28))
        struct.pack_into("<I", altered, 112, zlib.crc32(altered[120:]))
        path = Path(temp) / (str(sign) + ".cai")
        path.write_bytes(altered)
        variants.append(path)
    for network in variants:
        scores = probes(a.previous, network)
        baseline = [evaluate(fen) for fen in fens]
        for weight in [0, 10, 25, 50, 100]:
            actual = probes(a.engine, network, weight)
            numerators = [
                value * weight + base * (100 - weight)
                for value, base in zip(scores, baseline)
            ]
            expected = [
                number // 100 if number >= 0 else -((-number) // 100)
                for number in numerators
            ]
            assert (
                actual == expected
            ), "optimized evaluation changed old blend or mate clamp"
            checked += len(actual)
for bad in ["-1", "101", "4294967306", "18446744073709551615"]:
    execution = subprocess.run(
        [a.engine, "--net-probe", a.network, bad],
        input="",
        capture_output=True,
        text=True,
        timeout=5,
    )
    assert execution.returncode != 0, "invalid percentage wrapped into accepted integer"
options = {
    "Threads": 1,
    "Hash": 16,
    "EvalFile": a.network,
    "Use Neural": True,
    "Neural Weight": 10,
}
with (
    UciClient([a.previous], options, warmup_nodes=1) as previous,
    UciClient([a.engine], options, warmup_nodes=1) as current,
):
    with (a.output / "search.jsonl").open("w") as log:
        for fen in fens[::8]:
            observed = []
            for actor in [previous, current]:
                actor.send("ucinewgame")
                actor.send("isready")
                actor.until("readyok", 5)
                move, _, lines = actor.play(fen, [], nodes=10000)
                infos = [line for line in lines if line.startswith("info depth ")]
                assert infos
                fields = infos[-1].split()
                observed.append(
                    {
                        "move": move,
                        "depth": fields[fields.index("depth") + 1],
                        "score": fields[
                            fields.index("score") + 1 : fields.index("score") + 3
                        ],
                        "pv": fields[fields.index("pv") + 1 :],
                    }
                )
            assert (
                observed[0] == observed[1]
            ), "fixed-node search changed after score-preserving optimization"
            log.write(
                json.dumps(
                    {"fen": fen, "previous": observed[0], "current": observed[1]}
                )
                + "\n"
            )
summary = {
    "status": "passed",
    "profile": "diagnostic optimization parity",
    "evaluation_comparisons": checked,
    "fixed_node_search_comparisons": 32,
    "nodes_per_search": 10000,
    "weights": [0, 10, 25, 50, 100],
    "synthetic_extreme_bias_controls": 2,
    "positions_sha256": hashlib.sha256(text.encode()).hexdigest(),
    "previous_sha256": hashlib.sha256(Path(a.previous).read_bytes()).hexdigest(),
    "engine_sha256": hashlib.sha256(Path(a.engine).read_bytes()).hexdigest(),
    "network_sha256": hashlib.sha256(Path(a.network).read_bytes()).hexdigest(),
    "full_acceptance": False,
}
(a.output / "PARITY.json").write_text(json.dumps(summary, indent=2) + "\n")
print(json.dumps(summary))
