"""Diagnostic evidence collector. It cannot issue full acceptance."""

import argparse, hashlib, json, os, platform, shutil, subprocess, time
from pathlib import Path
from verification.source import PRODUCT, snapshot, verify_checkout


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write(path, data):
    Path(path).write_text(json.dumps(data, indent=2) + "\n")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--checkout", type=Path, required=True)
    ap.add_argument("--engine", type=Path, required=True)
    ap.add_argument("--network", type=Path, required=True)
    ap.add_argument("--arena", type=Path, required=True)
    ap.add_argument("--output", type=Path, required=True)
    a = ap.parse_args()
    root = a.checkout.resolve()
    engine = a.engine.resolve()
    out = a.output.resolve()
    out.mkdir(parents=True, exist_ok=False)
    (out / "bin").mkdir()
    (out / "logs").mkdir()
    if subprocess.check_output(["git", "status", "--porcelain"], cwd=root, text=True):
        raise ValueError("source checkout must be clean")
    commit = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=root, text=True
    ).strip()
    source = {
        "schema": "caissa-source-inputs-v2",
        "policy": PRODUCT,
        "commit": commit,
        "files": snapshot(root, commit, PRODUCT),
    }
    verify_checkout(root, source, commit, PRODUCT)
    write(out / "SOURCE_INPUTS.json", source)
    write(
        out / "ENVIRONMENT.json",
        {
            "platform": platform.platform(),
            "machine": platform.machine(),
            "cpu_count": os.cpu_count(),
            "python": platform.python_version(),
            "free_bytes": shutil.disk_usage(out).free,
        },
    )
    shutil.copy2(engine, out / "bin/caissa")
    shutil.copy2(a.network, out / "network.cai")
    write(
        out / "DATASETS.json",
        {
            "profile": "diagnostic",
            "network_sha256": sha(a.network),
            "full_corpus": None,
            "note": "No full data or learning gate is certified by this bundle.",
        },
    )
    commands = (out / "COMMANDS.jsonl").open("w")
    counter = 0

    def run(args, input=None):
        nonlocal counter
        start = time.monotonic()
        r = subprocess.run(
            args, input=input, capture_output=True, text=True, cwd=root, timeout=120
        )
        counter += 1
        log = f"logs/{counter:03d}.txt"
        (out / log).write_text(r.stdout + r.stderr)
        commands.write(
            json.dumps(
                {
                    "argv": args,
                    "cwd": str(root),
                    "exit": r.returncode,
                    "seconds": time.monotonic() - start,
                    "required": True,
                    "log": log,
                }
            )
            + "\n"
        )
        commands.flush()
        if r.returncode:
            raise ValueError("required command failed: " + str(args))
        return r.stdout

    run(["ctest", "--test-dir", str(engine.parent), "--output-on-failure"])
    fixtures = json.loads((root / "config/perft.json").read_text())["positions"]
    perft_rows = []
    for row in fixtures:
        args = [str(out / "bin/caissa"), "--perft", str(row["depth"]), row["fen"]] + (
            ["960"] if row["chess960"] else []
        )
        actual = int(run(args))
        perft_rows.append({"id": row["id"], "actual": actual})
        if actual != row["nodes"]:
            raise ValueError("perft known total mismatch")
    write(out / "perft.json", perft_rows)
    fens = [
        fixtures[0]["fen"],
        fixtures[1]["fen"],
        "7k/8/5KQ1/8/8/8/8/8 w - - 0 1",
        "7k/8/8/8/8/8/4P3/4K3 w - - 0 1",
    ]
    with (out / "search.jsonl").open("w") as log:
        for fen in fens:
            value = json.loads(run([str(out / "bin/caissa"), "--search", "4", fen]))
            value["fen"] = fen
            log.write(json.dumps(value) + "\n")
    import chess, random

    b = chess.Board()
    rng = random.Random(86028121)
    probes = []
    for i in range(64):
        if b.is_game_over():
            b = chess.Board()
        probes.append(b.fen(en_passant="fen"))
        b.push(rng.choice(list(b.legal_moves)))
    output = run(
        [str(out / "bin/caissa"), "--net-probe", str(out / "network.cai")],
        input="\n".join(probes) + "\n",
    )
    values = [json.loads(l) for l in output.splitlines()]
    if len(values) != len(probes):
        raise ValueError("network probe work missing")
    with (out / "network-probes.jsonl").open("w") as log:
        for fen, value in zip(probes, values):
            log.write(
                json.dumps(
                    {
                        "fen": fen,
                        "native": value["native"],
                        "reference": value["scalar"],
                    }
                )
                + "\n"
            )
    records = [
        json.loads(p.read_text()) for p in sorted((a.arena / "pairs").glob("*.json"))
    ]
    write(out / "arena-pairs.json", records)
    shutil.copy2(a.arena / "SUMMARY.json", out / "arena-summary.json")
    shutil.copy2(a.arena / "CONFIG.json", out / "arena-inputs.json")
    start = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"
    draws = [
        {
            "initial": start,
            "moves": ["g1f3", "g8f6", "f3g1", "f6g8"] * 2,
            "termination": "threefold-claim",
            "result": "1/2-1/2",
        },
        {
            "initial": "7k/6Q1/5K2/8/8/8/8/8 b - - 150 80",
            "moves": [],
            "termination": "checkmate",
            "result": "1-0",
        },
    ]
    write(out / "draw-probes.json", draws)
    commands.close()
    write(
        out / "ACCEPTANCE.json",
        {
            "profile": "diagnostic",
            "full_acceptance": False,
            "status": "unverified-until-independent-replay",
            "source_commit": commit,
            "pending": [
                "full data and all three full seed runs",
                "neural strength gain",
                "external strength campaign",
                "parallel race/performance campaign",
                "complete release audit",
            ],
        },
    )
    write(
        out / "COVERAGE.json",
        {
            "G01": "diagnostic perft execution plus separately recorded differential runs",
            "G02": "separate million-transition diagnostic",
            "G03": "draw-history fixtures and native tests",
            "G04": "separate adversarial protocol diagnostic",
            "G05": "native independent-minimax tests",
            "G06": "saved-network cross-language inference probes",
            "G07": "full learning pending",
            "G08": "diagnostic negative neural result retained",
            "G09": "full external campaign pending",
            "G10": "full thread campaign pending",
            "G11": "forced recovery pending",
            "G12": "live board trace recorded separately",
            "G13": "full performance campaign pending",
            "G14": "independent semantic verifier",
            "G15": "diagnostic clean-checkout execution",
            "G16": "incomplete",
        },
    )
    paths = sorted(p for p in out.rglob("*") if p.is_file())
    write(
        out / "MANIFEST.json",
        {"files": {str(p.relative_to(out)): sha(p) for p in paths}},
    )
    print(
        json.dumps(
            {
                "evidence": str(out),
                "source": commit,
                "profile": "diagnostic",
                "full_acceptance": False,
            }
        )
    )


if __name__ == "__main__":
    main()
