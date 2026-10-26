"""Independently reject consistently rehashed semantic witness forgeries.

Native observations are read only. No engine, training or producer is imported
or invoked. Four fixed families form G14; all other full gates stay separate.
"""

import argparse
import hashlib
import json
import shutil
import subprocess
import time
from pathlib import Path

import chess

from verification.bundle import Bundle, digest_text, strict_json
from verification.draw_history import expected, typed_equal
from verification.network_bytes import QuantizedNetwork
from verification.restoration_state import Shadow
from verification.source import PRODUCT, require, verify_checkout

PROFILE = "750a973a5a4d2f7d53238f204ef4b225d280854eb057d77900403f7d185d21ad"


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n")


def seal(root):
    files = {
        str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(root.rglob("*"))
        if p.is_file() and p.name != "MANIFEST.json"
    }
    write(root / "MANIFEST.json", {"files": files})
    return hashlib.sha256((root / "MANIFEST.json").read_bytes()).hexdigest()


def check(root, checkout, source, engine, network, pin, *, maximum_seconds=30):
    from verification.classical import evaluate
    from verification.match_journals import verify as journals
    from verification.verify import independent_statistics

    with Bundle(root, maximum_seconds) as bundle:
        require(
            hashlib.sha256(bundle.bytes("MANIFEST.json")).hexdigest()
            == digest_text(pin),
            "G14 external manifest identity differs",
        )
        bundle.verify_manifest()
        require(
            len(bundle.identities) <= 64, "G14 raw file count exceeds prospective bound"
        )
        require(
            sum((bundle.root / name).stat().st_size for name in bundle.identities)
            <= 8 * 1024**2,
            "G14 compact witness byte bound exceeded",
        )
        verify_checkout(checkout, bundle.json("SOURCE_INPUTS.json"), source, PRODUCT)
        config = bundle.json("CONFIG.json")
        require(
            config.get("schema") == "caissa-semantic-witness-v1"
            and config.get("source_commit") == source
            and config.get("engine_sha256") == engine
            and config.get("network_sha256") == network
            and config.get("profile_sha256") == PROFILE,
            "G14 source or saved input identities differ",
        )
        require(
            bundle.identities["engine"] == engine
            and bundle.identities["network.cai"] == network
            and bundle.identities["PROFILE.json"] == PROFILE,
            "G14 raw engine, network or frozen profile differs",
        )
        rule = bundle.json("PROFILE.json")
        require(
            network == rule["network_sha256"]
            and config.get("maximum_seconds") == 120
            and config.get("deadline_unix") == config.get("started_unix", 0) + 120,
            "G14 prospective witness contract changed",
        )
        witness = bundle.json("WITNESSES.json")
        require(
            set(witness) == {"searches", "inference", "draws"}
            and len(witness["searches"])
            == len(witness["inference"])
            == len(witness["draws"])
            == 4,
            "G14 witness family inventory differs",
        )
        commands = [
            strict_json(line) for line in bundle.bytes("COMMANDS.jsonl").splitlines()
        ]
        require(len(commands) == 5, "G14 bounded native command inventory differs")
        for index, (row, fen) in enumerate(
            zip(witness["searches"], rule["fens"], strict=True)
        ):
            bundle.tick()
            require(
                row.get("fen") == fen
                and row.get("exit") == 0
                and row.get("stderr") == "",
                "G14 search native transport differs",
            )
            require(
                commands[index]["command"][1:] == ["--search", "3", fen, "1"]
                and all(
                    typed_equal(row[k], commands[index][k])
                    for k in ["exit", "stdout", "stderr"]
                ),
                "G14 native search command or captured bytes differ",
            )
            actual = strict_json(row["stdout"])
            board = chess.Board(fen)
            variation = actual.get("pv")
            require(
                isinstance(variation, list)
                and 0 < len(variation) <= 64
                and actual.get("bestmove") == variation[0],
                "illegal semantic PV: missing or inconsistent native variation",
            )
            for text in variation:
                move = chess.Move.from_uci(text)
                require(
                    move in board.legal_moves,
                    "illegal semantic PV: independent board rejects move",
                )
                board.push(move)
        identity = bundle.json("arena/CONFIG.json")
        game_config = identity["config"]
        require(
            game_config["pairs"] == 2
            and game_config["nodes"] == 1000
            and game_config["max_plies"] == 64
            and identity["openings_sha256"] == bundle.identities["OPENINGS.json"],
            "G14 fixed diagnostic game schedule differs",
        )
        openings = bundle.json("OPENINGS.json")["openings"]
        require(
            openings
            == [
                {"id": "g14-mate-" + str(i), "fen": fen, "moves": []}
                for i, fen in enumerate(rule["mate_fens"])
            ],
            "G14 actual fixed mate openings differ",
        )
        for role in ["candidate", "opponent"]:
            require(
                identity["executables"][role]["executable"] == engine
                and game_config[role]["options"]
                == {"Threads": 1, "Hash": 1, "Use Neural": False},
                "G14 diagnostic game actor differs",
            )
        pairs = [bundle.json(f"arena/pairs/{i:06d}.json") for i in range(2)]
        try:
            for i, pair in enumerate(pairs):
                require(
                    pair["opening_id"] == openings[i]["id"],
                    "fixed opening identity differs",
                )
                for game in pair["games"]:
                    require(
                        game["initial"] == rule["mate_fens"][i]
                        and game["termination"] == "checkmate"
                        and len(game["moves"]) == 1,
                        "fixed native mate witness differs",
                    )
            journal_result = journals(
                bundle.root / "arena",
                maximum_seconds=min(15, maximum_seconds),
                tick=bundle.tick,
            )
            stats = independent_statistics(pairs, tick=bundle.tick)
            require(
                (
                    stats["wins"],
                    stats["draws"],
                    stats["losses"],
                    stats["unfinished_games"],
                )
                == (2, 0, 2, 0),
                "independent diagnostic color statistics differ",
            )
        except ValueError as error:
            raise ValueError("swapped result colors: " + str(error)) from error
        net = QuantizedNetwork(bundle.root / "network.cai")
        require(
            net.identity == rule["checkpoint_sha256"], "G14 selected checkpoint differs"
        )
        for row, fen in zip(witness["inference"], rule["fens"], strict=True):
            bundle.tick()
            require(
                row.get("fen") == fen
                and row.get("exit") == 0
                and row.get("stderr") == "",
                "G14 inference native transport differs",
            )
            actual = strict_json(row["stdout"])
            total = net.infer(fen) * 10 + evaluate(fen) * 90
            score = (1 if total >= 0 else -1) * (abs(total) // 100)
            require(
                type(actual.get("scalar")) is int
                and type(actual.get("native")) is int
                and actual["scalar"] == actual["native"] == score
                and actual["lower"] <= score <= actual["upper"],
                "mismatched network inference: independent integer interpretation differs",
            )
        for row, commands in zip(witness["draws"], rule["draw_histories"], strict=True):
            bundle.tick()
            require(
                row.get("commands") == commands,
                "G14 actual draw history schedule differs",
            )
            shadow = Shadow(net)
            for command in commands:
                if command.startswith("reset "):
                    shadow.reset(command[6:])
                else:
                    shadow.push(command[5:])
            require(
                typed_equal(strict_json(row["rules_stdout"]), expected(shadow)),
                "incorrect draw claim: independent history reconstruction differs",
            )
        return {
            "status": "passed",
            "witness_pass": True,
            "source_commit": source,
            "engine_sha256": engine,
            "network_sha256": network,
            "searches": 4,
            "game_journals": journal_result["game_journals"],
            "selected_network_inferences": 4,
            "draw_histories": 4,
            "full_gate": False,
            "full_acceptance": False,
        }


def mutate(root, family, variant):
    """Alter semantics and update every ordinary duplicate/hash consistently."""
    path = root / "WITNESSES.json"
    value = strict_json(path.read_bytes())
    if family == "illegal-pv":
        row = value["searches"][variant]
        response = strict_json(row["stdout"])
        response["pv"][0] = response["bestmove"] = "a1a8"
        row["stdout"] = json.dumps(response) + "\n"
        commands = [
            strict_json(line)
            for line in (root / "COMMANDS.jsonl").read_bytes().splitlines()
        ]
        commands[variant]["stdout"] = row["stdout"]
        (root / "COMMANDS.jsonl").write_text(
            "".join(json.dumps(row) + "\n" for row in commands)
        )
    elif family == "mismatched-network-inference":
        row = value["inference"][variant]
        response = strict_json(row["stdout"])
        response["scalar"] += 1
        response["native"] += 1
        row["stdout"] = json.dumps(response) + "\n"
    elif family == "incorrect-draw-claim":
        row = value["draws"][variant]
        response = strict_json(row["rules_stdout"])
        field = "threefold_claim" if variant % 2 == 0 else "fifty_move_claim"
        response[field] = not response[field]
        response["claimable"] = (
            response["threefold_claim"] or response["fifty_move_claim"]
        )
        row["rules_stdout"] = json.dumps(response)
    elif family == "swapped-result-colors":
        number, reverse = divmod(variant, 2)
        pair_path = root / f"arena/pairs/{number:06d}.json"
        pair = strict_json(pair_path.read_bytes())
        game = pair["games"][reverse]
        if variant % 2 == 0:
            old = game["result"]
            game["result"] = "0-1" if old == "1-0" else "1-0"
            pgn = root / f"arena/games/{number:06d}-{reverse}.pgn"
            pgn.write_text(pgn.read_text().replace(old, game["result"]))
        else:
            game["candidate_color"] = (
                "white" if game["candidate_color"] == "black" else "black"
            )
        write(pair_path, pair)
        write(root / f"arena/games/{number:06d}-{reverse}.json", game)
    else:
        raise ValueError("unsupported G14 semantic mutation")
    write(path, value)
    return seal(root)


def audit(root, checkout, source, engine, network, pin, output):
    root, output = Path(root).resolve(), Path(output).resolve()
    require(
        not output.is_relative_to(root) and not root.is_relative_to(output),
        "G14 audit output must preserve original witnesses",
    )
    output.mkdir(parents=True, exist_ok=False)
    start, wall = time.monotonic(), time.time()
    deadline = wall + 180
    positive = check(root, checkout, source, engine, network, pin)
    rule = strict_json((root / "PROFILE.json").read_bytes())
    results = []
    for family in rule["families"]:
        for variant in range(rule["variants_per_family"]):
            require(
                time.time() < deadline and time.monotonic() - start < 180,
                "G14 cumulative audit ceiling exhausted",
            )
            target = output / (family + "-" + str(variant))
            shutil.copytree(root, target)
            changed_pin = mutate(target, family, variant)
            try:
                check(target, checkout, source, engine, network, changed_pin)
            except ValueError as error:
                reason = str(error)
                required = {
                    "illegal-pv": "illegal semantic PV",
                    "swapped-result-colors": "swapped result colors",
                    "mismatched-network-inference": "mismatched network inference",
                    "incorrect-draw-claim": "incorrect draw claim",
                }[family]
                require(
                    required in reason,
                    "G14 forgery failed before its independent semantic check: "
                    + reason,
                )
                results.append(
                    {
                        "family": family,
                        "variant": variant,
                        "rejection": reason,
                        "rehashed_manifest_sha256": changed_pin,
                    }
                )
            else:
                raise ValueError(
                    "G14 rehashed semantic forgery was accepted: " + family
                )
            write(output / "REJECTIONS.json", results)
            require(
                sum(p.stat().st_size for p in output.rglob("*") if p.is_file())
                <= 512 * 1024**2
                and shutil.disk_usage(output).free >= 10 * 1024**3,
                "G14 audit original output or free-space bound exhausted",
            )
    require(len(results) == 16, "G14 mutation inventory is incomplete")
    native_binding = None
    if engine == rule["saved_engine_sha256"]:
        from verification.runtime_binding import inspect

        native_binding = inspect(
            checkout,
            source,
            root / "V4.json",
            hashlib.sha256((root / "V4.json").read_bytes()).hexdigest(),
            root / "engine",
            root / "network.cai",
            root / "MODEL_CAMPAIGN.json",
        )
    require(
        hashlib.sha256((root / "MANIFEST.json").read_bytes()).hexdigest() == pin,
        "G14 original manifest changed during audit",
    )
    result = {
        "status": "passed",
        "gate": "G14",
        "source_commit": source,
        "engine_sha256": engine,
        "network_sha256": network,
        "original_manifest_sha256": pin,
        "positive_witnesses": positive,
        "rehashed_semantic_rejections": results,
        "saved_native_source_binding": native_binding,
        "full_gate": native_binding is not None,
        "full_acceptance": False,
        "scope": "Four required G14 forgery families only. No other runtime, learning, strength, browser or release gate is certified.",
        "elapsed_seconds": time.monotonic() - start,
    }
    write(output / "G14.json", result)
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=["check", "audit"])
    parser.add_argument("root", type=Path)
    parser.add_argument("--checkout", type=Path, required=True)
    parser.add_argument("--expected-commit", required=True)
    parser.add_argument("--expected-engine-sha256", required=True)
    parser.add_argument("--expected-network-sha256", required=True)
    parser.add_argument("--expected-manifest-sha256", required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        arguments = [
            args.root,
            args.checkout,
            args.expected_commit,
            args.expected_engine_sha256,
            args.expected_network_sha256,
            args.expected_manifest_sha256,
        ]
        require(
            args.mode == "check" or args.output is not None,
            "G14 audit requires a separate output",
        )
        result = (
            check(*arguments)
            if args.mode == "check"
            else audit(*arguments, args.output)
        )
        print(json.dumps(result))
    except (
        ValueError,
        OSError,
        KeyError,
        TypeError,
        IndexError,
        subprocess.SubprocessError,
    ) as error:
        print(
            json.dumps(
                {
                    "status": "rejected",
                    "reason": str(error),
                    "full_gate": False,
                    "full_acceptance": False,
                }
            )
        )
        raise SystemExit(1)


if __name__ == "__main__":
    main()
