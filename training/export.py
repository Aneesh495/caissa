import argparse, json, hashlib
from pathlib import Path
import torch
from training.model import CaissaNet, export_network


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("checkpoint", type=Path)
    ap.add_argument("output", type=Path)
    ap.add_argument(
        "--export-format",
        type=int,
        choices=[4],
        help="Explicit experimental precision conversion; trained float parameters stay unchanged",
    )
    a = ap.parse_args()
    checkpoint = torch.load(a.checkpoint, map_location="cpu", weights_only=False)
    if checkpoint.get("schema") != "caissa-checkpoint-v1":
        raise ValueError("unsupported checkpoint")
    model = CaissaNet(
        version=int(
            checkpoint["config"].get("network_contract", "v1").split("-")[0][1:]
        ),
        width=checkpoint["config"].get("width", 64),
    )
    model.load_state_dict(checkpoint["model"], strict=True)
    print(
        json.dumps(
            export_network(
                model,
                a.output,
                hashlib.sha256(a.checkpoint.read_bytes()).hexdigest(),
                a.export_format,
            )
        )
    )


if __name__ == "__main__":
    main()
