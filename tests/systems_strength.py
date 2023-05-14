"""Rehashed changes cannot become a full thread/heuristic strength comparison.

Positive cases admit metadata only. The CLI uses four genuine CI game journals
to prove that invented full-sample metadata cannot certify missing observations.
"""

import argparse
import copy
import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

from tools.campaign_process import atomic
from verification.systems_strength import admission, contract


def profile(kind):
    switches = [
        ("null", "Null Move"),
        ("lmr", "LMR"),
        ("extensions", "Extensions"),
        ("futility", "Futility"),
        ("see", "SEE"),
        ("history", "History"),
        ("pvs", "PVS"),
        ("aspiration", "Aspiration"),
        ("quiescence", "Quiescence"),
        ("table", "Use Table"),
    ]
    if kind == "parallel":
        rows = [
            {
                "id": f"threads-{n}-ms-{ms}",
                "threads": n,
                "switch": None,
                "budget_kind": "milliseconds",
                "budget": ms,
                "pairs": 100,
            }
            for n in [2, 4, 8]
            for ms in [100, 400]
        ]
    else:
        rows = [
            {
                "id": f"{short}-{key}-{n}",
                "threads": 1,
                "switch": name,
                "budget_kind": key,
                "budget": n,
                "pairs": count,
            }
            for short, name in switches
            for key, numbers, count in [
                ("milliseconds", [100, 400], 50),
                ("nodes", [20000, 100000], 25),
            ]
            for n in numbers
        ]
    seconds = 28800 if kind == "parallel" else 43200
    return {
        "schema": "caissa-systems-strength-protocol-v1",
        "status": "frozen",
        "base_protocol_sha256": "a8623bf2d59561d434546ad612c939f994a4e699b1c61f4eba5b3114f26528dd",
        "kind": kind,
        "comparisons": rows,
        "resources": {
            "maximum_wall_seconds": seconds,
            "maximum_active_seconds": seconds,
            "maximum_attempts": 3,
            "maximum_additional_bytes": 20 * 1024**3,
            "minimum_free_bytes": 10 * 1024**3,
            "workers": 1 if kind == "parallel" else 2,
            "parent_deadline_unix": 1793150297.974828,
            "output": f"runs/full-{kind}-strength-v1",
        },
    }


def actors(rule, original, row, declarations):
    toggles = [
        "Null Move",
        "LMR",
        "Extensions",
        "Futility",
        "SEE",
        "History",
        "PVS",
        "Aspiration",
        "Quiescence",
        "Use Table",
    ]
    identity = {
        "config": {
            "profile": "full original " + rule["kind"] + " comparison",
            "openings": "/saved/OPENINGS.json",
            "pairs": row["pairs"],
            row["budget_kind"]: row["budget"],
            "max_plies": 512,
            "warmup_nodes": 1,
            "transport_allowance_ms": 150,
        },
        "executables": {},
        "openings_sha256": original["strength_actor"]["openings_sha256"],
    }
    wire = {}
    for role in ["candidate", "opponent"]:
        neural = rule["kind"] == "parallel"
        options = {
            "Threads": row["threads"] if role == "candidate" else 1,
            "Hash": 16,
            "Use Neural": neural,
            "Evaluation Cache": True,
            "Tactical Generation": True,
            "Lazy Neural": True,
            "Neural Bounds": False,
            "Ordering Hints": False,
            **{name: True for name in toggles},
        }
        if neural:
            options.update({"Neural Weight": 10, "EvalFile": "/saved/selected.cai"})
        elif role == "opponent":
            options[row["switch"]] = False
        configured = {"name": role, "command": ["/saved/caissa"], "options": options}
        identity["config"][role] = configured
        identity["executables"][role] = {
            "executable": original["strength_actor"]["engine_sha256"],
            "command": configured["command"],
            "options": options,
        }
        if neural:
            identity["executables"][role]["network_sha256"] = original[
                "strength_actor"
            ]["network_sha256"]
        wire[role] = copy.deepcopy(declarations[role])
    sync_commands(identity, wire)
    return identity, wire


def sync_commands(identity, wire):
    for role in ["candidate", "opponent"]:
        actor = identity["executables"][role]
        wire[role]["executable_sha256"] = actor["executable"]
        wire[role]["configuration_commands"] = [
            f"setoption name {key} value {str(value).lower() if type(value) is bool else value}"
            for key, value in actor["options"].items()
        ]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--campaign", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    root = Path(__file__).resolve().parents[1]
    base = root / "config/protocol-v4.json"
    declarations = json.loads((args.campaign / "PROTOCOL.json").read_text())
    admitted = []
    for kind, comparisons, games in [("parallel", 6, 1200), ("heuristics", 40, 3000)]:
        path = args.output / (kind + ".json")
        atomic(path, profile(kind))
        rule, original, _ = contract(path, base)
        assert len(rule["comparisons"]) == comparisons
        assert sum(2 * row["pairs"] for row in rule["comparisons"]) == games
        for row in rule["comparisons"]:
            identity, wire = actors(rule, original, row, declarations)
            admission(identity, wire, rule, original, row)
            admitted.append(row["id"])

    cases = [
        "small-real-sample",
        "unknown-schema",
        "missing-comparison",
        "reordered-matrix",
        "duplicated-comparison",
        "boolean-pairs",
        "smaller-node-budget",
        "longer-scope",
        "extended-parent",
        "changed-workers",
        "extra-option",
        "integer-lazy",
        "weakened-control",
        "wrong-reference-threads",
        "both-smaller-hash",
        "different-executable",
        "command-wrapper",
        "changed-model",
        "changed-mixture",
        "different-eval-file",
        "changed-uci-commands",
        "undeclared-option",
        "uci-range",
        "missing-deployment-option",
        "changed-openings",
        "mixed-budgets",
        "different-classical-heuristic",
        "neural-heuristic-control",
    ]
    controls = []
    for case in cases:
        folder = args.output / case
        shutil.copytree(args.campaign, folder / "raw")
        kind = (
            "heuristics"
            if case
            in {
                "different-classical-heuristic",
                "neural-heuristic-control",
                "smaller-node-budget",
            }
            else "parallel"
        )
        rule = profile(kind)
        if case == "smaller-node-budget":
            rule["comparisons"][2]["budget"] = 10000
        if case == "unknown-schema":
            rule["schema"] += "-future"
        elif case == "missing-comparison":
            rule["comparisons"].pop()
        elif case == "reordered-matrix":
            rule["comparisons"].reverse()
        elif case == "duplicated-comparison":
            rule["comparisons"][1] = copy.deepcopy(rule["comparisons"][0])
        elif case == "boolean-pairs":
            rule["comparisons"][0]["pairs"] = True
        elif case == "longer-scope":
            rule["resources"]["maximum_wall_seconds"] += 1
        elif case == "extended-parent":
            rule["resources"]["parent_deadline_unix"] += 1
        elif case == "changed-workers":
            rule["resources"]["workers"] = 2
        row = rule["comparisons"][0]
        original = json.loads(base.read_text())
        identity, wire = actors(rule, original, row, declarations)
        left, right = (
            identity["executables"]["candidate"],
            identity["executables"]["opponent"],
        )
        if case == "extra-option":
            left["options"]["Scalar Neural"] = True
        elif case == "integer-lazy":
            left["options"]["Lazy Neural"] = 1
        elif case == "weakened-control":
            right["options"]["Use Table"] = False
        elif case == "wrong-reference-threads":
            right["options"]["Threads"] = 2
        elif case == "both-smaller-hash":
            for actor in [left, right]:
                actor["options"]["Hash"] = 8
        elif case == "different-executable":
            right["executable"] = "a" * 64
        elif case == "command-wrapper":
            left["command"].append("--weaker")
        elif case == "changed-model":
            left["network_sha256"] = "b" * 64
        elif case == "changed-mixture":
            left["options"]["Neural Weight"] = 25
        elif case == "different-eval-file":
            right["options"]["EvalFile"] = "/saved/other.cai"
        elif case == "missing-deployment-option":
            del left["options"]["Lazy Neural"]
        elif case == "changed-openings":
            identity["openings_sha256"] = "d" * 64
        elif case == "mixed-budgets":
            identity["config"]["nodes"] = 1000
        elif case == "different-classical-heuristic":
            right["options"]["LMR"] = False
        elif case == "neural-heuristic-control":
            right["options"]["Use Neural"] = True
        sync_commands(identity, wire)
        if case == "changed-uci-commands":
            wire["opponent"]["configuration_commands"].pop()
        elif case == "undeclared-option":
            del wire["candidate"]["declared_options"]["Hash"]
        elif case == "uci-range":
            wire["candidate"]["declared_options"]["Hash"]["max"] = "8"
        atomic(folder / "PROFILE.json", rule)
        atomic(folder / "raw/CONFIG.json", identity)
        atomic(folder / "raw/PROTOCOL.json", wire)
        pin = hashlib.sha256((folder / "PROFILE.json").read_bytes()).hexdigest()
        command = [
            sys.executable,
            "-m",
            "verification.systems_strength",
            str(folder / "raw"),
            "--profile",
            str(folder / "PROFILE.json"),
            "--expected-profile-sha256",
            pin,
            "--comparison",
            row["id"],
            "--maximum-seconds",
            "30",
        ]
        run = subprocess.run(command, capture_output=True, text=True, timeout=35)
        (folder / "rejection.log").write_text(run.stdout + run.stderr)
        value = json.loads(run.stdout)
        assert run.returncode == 1 and value["status"] == "rejected", (
            case,
            run.returncode,
            value,
        )
        expected = {
            "small-real-sample": "file inventory differs",
            "unknown-schema": "schema",
            "missing-comparison": "matrix",
            "reordered-matrix": "matrix",
            "duplicated-comparison": "matrix",
            "boolean-pairs": "matrix",
            "smaller-node-budget": "matrix",
            "longer-scope": "resource",
            "extended-parent": "resource",
            "changed-workers": "resource",
            "different-executable": "executable",
            "command-wrapper": "command identity",
            "changed-model": "network",
            "different-eval-file": "identical saved",
            "changed-uci-commands": "UCI commands",
            "undeclared-option": "UCI declaration",
            "uci-range": "UCI declaration",
            "changed-openings": "opening identity",
            "mixed-budgets": "inventory",
        }.get(case, "unrelated search option")
        assert expected in value["reason"], (case, expected, value)
        controls.append(
            {"case": case, "actual_exit": run.returncode, "observed": value}
        )
    result = {
        "status": "passed",
        "metadata_comparisons_admitted": len(admitted),
        "controls": controls,
        "positive_full_sample_replayed": False,
        "production_profiles_frozen": False,
        "full_G10_certified": False,
        "full_acceptance": False,
    }
    atomic(args.output / "CONTROLS.json", result)
    print(json.dumps(result))


if __name__ == "__main__":
    main()
