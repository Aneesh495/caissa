"""Frozen heuristic samples and rehashed negative evidence controls."""

import argparse
import copy
import fcntl
import json
import tempfile
from pathlib import Path
from types import SimpleNamespace

from tools.heuristic_study import contract, options, summarize
from verification.acquisition import sha
from verification.heuristic_study import expected_options, verify


def contracts():
    path = Path("config/heuristic-study-v1.json")
    rule, cases = contract(path, sha(path))
    assert len(cases) == 8
    flags = {
        "null": "Null Move",
        "lmr": "LMR",
        "extensions": "Extensions",
        "futility": "Futility",
        "see": "SEE",
        "history": "History",
        "pvs": "PVS",
        "aspiration": "Aspiration",
        "quiescence": "Quiescence",
        "table": "Use Table",
    }
    base = options("reference")
    assert all(base[key] is True for key in flags.values())
    assert base["Use Neural"] is False and base["Threads"] == 1 and base["Hash"] == 16
    for mode, flag in flags.items():
        changed = options(mode)
        assert changed == expected_options(mode)
        assert {key for key in base if base[key] != changed[key]} == {flag}
        assert changed[flag] is False
    rejected = []
    with tempfile.TemporaryDirectory(prefix="caissa-heuristic-contracts-") as folder:
        target = Path(folder) / "protocol.json"
        for key, value in [
            ("schema", "caissa-heuristic-study-v0"),
            ("status", "draft"),
            ("profile", "full"),
            ("positions", "elsewhere.json"),
            ("positions_sha256", "0" * 64),
            ("nodes", [5000]),
            ("milliseconds", [25]),
            ("repeats", 2),
            ("schedule_seed", 0),
            ("threads", 2),
            ("threads", True),
            ("hash_mib", 32),
            ("warmup_nodes", 0),
            ("maximum_seconds", 601),
            ("maximum_observation_bytes", 134217729),
        ]:
            changed = copy.deepcopy(rule)
            changed[key] = value
            target.write_text(json.dumps(changed))
            try:
                contract(target, sha(target))
            except ValueError:
                rejected.append({"field": key, "value": value})
            else:
                raise AssertionError("changed heuristic contract admitted: " + key)
        target.write_text(json.dumps(rule))
        try:
            contract(target, "0" * 64)
        except ValueError:
            rejected.append({"field": "external protocol identity"})
        else:
            raise AssertionError("external protocol hash ignored")
    # The collector and independent replay must both defer to actual owner locks.
    from tools.heuristic_study import avoid_decisive_matches
    from verification.heuristic_study import defer_matches

    with tempfile.TemporaryDirectory(prefix="caissa-heuristic-lock-") as folder:
        root = Path(folder)
        target = root / "full-neural-strength-v3" / "OWNER.lock"
        target.parent.mkdir()
        with target.open("a") as stream:
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            for check in [avoid_decisive_matches, defer_matches]:
                try:
                    check(root)
                except ValueError as error:
                    assert "defer" in str(error)
                else:
                    raise AssertionError("live decisive host lock ignored")
    return {
        "status": "passed",
        "single_switch_modes": 10,
        "rejected_contracts": rejected,
        "actual_owner_lock_deferrals": 2,
        "full_acceptance": False,
    }


def controls(args):
    args.output.mkdir(parents=True, exist_ok=False)
    originals = {
        name: (args.evidence / name).read_bytes()
        for name in [
            "CONFIG.json",
            "SUMMARY.json",
            "SESSIONS.json",
            "observations.jsonl",
        ]
    }
    original_rows = [
        json.loads(line) for line in originals["observations.jsonl"].splitlines()
    ]
    results = []
    for name, reason in [
        ("weakened-reference", "control was weakened"),
        ("wrong-session-options", "actual heuristic session options"),
        ("duplicate-query", "actual schedule differs"),
        ("changed-node-command", "actual heuristic position or budget"),
        ("illegal-pv", "illegal PV"),
        ("changed-parsed-score", "metadata differs"),
        ("negative-work", "invalid native work counter"),
        ("disabled-work", "disabled heuristic still reported"),
        ("fabricated-summary", "work, depth or decision summary"),
        ("short-sample", "fixed sample is incomplete"),
        ("invented-elo", "cannot claim strength"),
        ("consistent-false-score", "fixed-node replay differs"),
    ]:
        folder = args.output / name
        folder.mkdir()
        for filename, data in originals.items():
            (folder / filename).write_bytes(data)
        rows = copy.deepcopy(original_rows)
        config, summary = json.loads(originals["CONFIG.json"]), json.loads(
            originals["SUMMARY.json"]
        )
        sessions = json.loads(originals["SESSIONS.json"])
        row = next(
            row
            for row in rows
            if row["budget_kind"] == "nodes"
            and row["observed"].get("score_type") == "cp"
        )
        if name == "weakened-reference":
            config["modes"]["reference"]["LMR"] = False
        elif name == "wrong-session-options":
            sessions["reference"]["configuration_commands"][
                0
            ] = "setoption name Threads value 2"
        elif name == "duplicate-query":
            rows[1] = copy.deepcopy(rows[0])
        elif name == "changed-node-command":
            row["request"]["go"] = "go nodes 1"
        elif name == "illegal-pv":
            row["uci"].insert(-1, "info depth 1 score cp 0 nodes 1 pv 0000")
        elif name == "changed-parsed-score":
            row["observed"]["score"] += 1
        elif name in ("negative-work", "disabled-work"):
            if name == "negative-work":
                key, value = "eval_calls", -1
            else:
                row = next(row for row in rows if row["mode"] == "null")
                key, value = "null_cutoffs", 1
            row["observed"]["stats"][key] = value
            for i, line in enumerate(row["uci"]):
                if line.startswith("info string stats "):
                    tokens = line.split()
                    tokens[tokens.index(key) + 1] = str(value)
                    row["uci"][i] = " ".join(tokens)
        elif name == "fabricated-summary":
            summary["groups"]["reference:nodes:5000"]["visited_nodes"] += 1
        elif name == "short-sample":
            rows.pop()
        elif name == "invented-elo":
            summary["absolute_elo"] = 3000
        else:
            row["observed"]["score"] += 1
            at = max(
                i for i, line in enumerate(row["uci"]) if line.startswith("info depth ")
            )
            tokens = row["uci"][at].split()
            tokens[tokens.index("score") + 2] = str(row["observed"]["score"])
            row["uci"][at] = " ".join(tokens)
            summary["groups"] = summarize(rows)
        (folder / "CONFIG.json").write_text(json.dumps(config) + "\n")
        (folder / "SESSIONS.json").write_text(json.dumps(sessions) + "\n")
        raw = folder / "observations.jsonl"
        raw.write_text(
            "".join(json.dumps(row, separators=(",", ":")) + "\n" for row in rows)
        )
        summary["observations_sha256"] = sha(raw)
        (folder / "SUMMARY.json").write_text(json.dumps(summary) + "\n")
        verification = SimpleNamespace(
            evidence=folder,
            engine=args.engine,
            expected_engine_sha256=args.expected_engine_sha256,
            protocol=Path("config/heuristic-study-v1.json"),
            expected_protocol_sha256=sha(Path("config/heuristic-study-v1.json")),
            output=args.output / (name + "-replay"),
            maximum_seconds=120,
        )
        try:
            verify(verification)
        except ValueError as error:
            assert reason in str(error), (name, str(error))
            results.append(
                {
                    "case": name,
                    "rejected": True,
                    "reason": str(error),
                    "rehashed_observations_sha256": summary["observations_sha256"],
                }
            )
        else:
            raise AssertionError("rehashed heuristic corruption admitted: " + name)
    assert all(
        (args.evidence / name).read_bytes() == data for name, data in originals.items()
    )
    result = {"status": "passed", "controls": results, "full_acceptance": False}
    (args.output / "CONTROLS.json").write_text(json.dumps(result, indent=2) + "\n")
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--evidence", type=Path)
    parser.add_argument("--engine", type=Path)
    parser.add_argument("--expected-engine-sha256")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    print(json.dumps(controls(args) if args.evidence else contracts()))


if __name__ == "__main__":
    main()
