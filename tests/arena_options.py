"""Actual native handshakes must reject falsely configured match settings."""

import argparse
from arena.client import EngineFailure, UciClient

parser = argparse.ArgumentParser()
parser.add_argument("--engine", default="build/caissa")
args = parser.parse_args()
for invalid in [
    {"Undeclared": True},
    {"Hash": 0},
    {"Threads": 9},
    {"Use Neural": "true"},
    {"Hash": True},
]:
    try:
        with UciClient([args.engine], invalid):
            pass
    except EngineFailure:
        pass
    else:
        raise ValueError("invalid actual match setting accepted: " + str(invalid))
with UciClient([args.engine], {"Hash": 1, "Threads": 1, "Use Neural": False}) as native:
    assert native.available_options["Threads"]["max"] == "8"
    assert any(line.startswith("id name ") for line in native.handshake)
    move, _, _ = native.play("7k/8/5KQ1/8/8/8/8/8 w - - 0 1", [], nodes=1000)
    assert move != "0000"
print(
    "five invalid match option contracts rejected; real native handshake and play accepted"
)
