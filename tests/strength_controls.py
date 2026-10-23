"""Real replay must reject rehashed requests, colors and principal variations."""

import argparse, json, shutil, subprocess, sys
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--campaign", type=Path, required=True)
    parser.add_argument("--openings", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    original = json.loads((args.campaign / "CONFIG.json").read_text())
    if args.openings is None:
        args.openings = Path(original["config"]["openings"])
    engine = original["executables"]["candidate"]["executable"]
    results = []
    for name, reason in [
        ("illegal-pv", "principal variation"),
        ("wrong-budget", "budget/history"),
        ("swapped-colors", "swapped result colors"),
        ("missing-observation", "matching raw protocol"),
    ]:
        folder = args.output / name
        shutil.copytree(args.campaign, folder)
        path = next(iter(sorted((folder / "pairs").glob("*.json"))))
        pair = json.loads(path.read_text())
        game = pair["games"][0]
        if name == "swapped-colors":
            game["candidate_color"] = "black"
        elif name == "missing-observation":
            game["observations"] = [
                row
                for row in game["observations"]
                if row.get("ply") != game["opening_plies"]
            ]
        else:
            row = next(row for row in game["observations"] if "move" in row)
            if name == "wrong-budget":
                row["request"]["go"] = "go nodes 1"
            else:
                row["uci"].insert(-1, "info depth 1 score cp 0 nodes 1 pv a1a1")
        path.write_text(json.dumps(pair) + "\n")
        command = [
            sys.executable,
            "-m",
            "verification.strength",
            str(folder),
            "--openings",
            str(args.openings),
            "--engine-sha256",
            engine,
        ]
        result = subprocess.run(command, capture_output=True, text=True, timeout=60)
        if result.returncode != 1:
            raise ValueError("strength corruption accepted: " + name)
        receipt = json.loads(result.stdout)
        if reason not in receipt["reason"]:
            raise ValueError("unrelated rejection " + name + ": " + receipt["reason"])
        results.append(
            {
                "case": name,
                "subprocess_exit": result.returncode,
                "reason": receipt["reason"],
            }
        )
    (args.output / "CONTROLS.json").write_text(json.dumps(results, indent=2) + "\n")
    print(json.dumps(results))


if __name__ == "__main__":
    main()
