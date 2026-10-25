"""Fixed-sample strength owner with persistent ceilings and controlled host load.

Uses the validation-selected original model even when a learning domain failed.
A failed neural gain never changes seeds, time controls or external settings.
"""

import argparse
import json
import os
import platform
import shutil
import subprocess
import sys
import time
from pathlib import Path

from tools.campaign_process import Campaign, StageFailure, atomic
from tools.finalize_corpus import archive_source
from tools.full_learning import frozen_rule
from tools.power_guard import PowerGuard
from tools.recovery_scope import RecoveryScope
from verification.acquisition import sha
from verification.protocol import read_json
from verification.verify import source_files

FORBIDDEN_MODULES = {
    "training.corpus",
    "training.prepare",
    "training.train",
    "training.baselines",
    "verification.dataset",
    "tools.finalize_corpus",
    "tools.full_learning",
    "arena.run",
    "tools.full_strength",
    "tools.performance",
    "tools.neural_cost",
    "verification.learning",
    "verification.numerical",
    "verification.performance",
    "verification.native_build",
}
COMPILERS = {
    "clang",
    "clang++",
    "cc1",
    "cc1plus",
    "gcc",
    "g++",
    "cc",
    "c++",
    "ninja",
    "make",
    "cmake",
    "ctest",
}


def process_rows():
    raw = subprocess.check_output(
        ["ps", "-axo", "pid=,ppid=,state=,%cpu=,command="], text=True, timeout=3
    )
    if len(raw.encode()) > 2 * 1024 * 1024:
        raise ValueError("host process inventory exceeds finite ceiling")
    rows = []
    for line in raw.splitlines():
        fields = line.strip().split(None, 4)
        if len(fields) != 5:
            raise ValueError("unparseable host process inventory")
        pid, ppid, state, cpu, command = fields
        rows.append(
            {
                "pid": int(pid),
                "ppid": int(ppid),
                "state": state,
                "cpu": float(cpu),
                "command": command[:2048],
            }
        )
    return rows


def offenders(rows, owner):
    owned = {owner}
    while True:
        more = {row["pid"] for row in rows if row["ppid"] in owned}
        if more <= owned:
            break
        owned |= more
    found = []
    for row in rows:
        if row["pid"] in owned or row["state"].startswith("Z"):
            continue
        tokens = row["command"].split()
        executable = Path(tokens[0]).name if tokens else ""
        module = (
            tokens[tokens.index("-m") + 1]
            if "-m" in tokens and tokens.index("-m") + 1 < len(tokens)
            else None
        )
        # Resumed owners use an explicit archived-source runpy launcher rather
        # than -m. Direct source paths are also recognized for known producers.
        python_work = executable.startswith("python") and any(
            token in FORBIDDEN_MODULES
            or any(
                token == name.replace(".", "/") + ".py"
                or token.endswith("/" + name.replace(".", "/") + ".py")
                for name in FORBIDDEN_MODULES
            )
            for token in tokens[1:]
        )
        if executable in COMPILERS or module in FORBIDDEN_MODULES or python_work:
            found.append(row)
    return found


class HostGuard:
    def __init__(self, output, scope, power=None):
        self.output, self.scope = output, scope
        self.power = power
        self.last = -1e9

    def check(self):
        self.scope.check()
        if self.power is not None:
            self.power.check()
        if time.monotonic() - self.last < 5:
            return
        rows = process_rows()
        bad = offenders(rows, os.getpid())
        top = sorted(rows, key=lambda row: row["cpu"], reverse=True)[:12]
        snapshot = {
            "unix": time.time(),
            "load": list(os.getloadavg()),
            "offenders": bad,
            "top_processes": top,
        }
        path = self.output / "HOST_SAMPLES.jsonl"
        if path.exists() and path.stat().st_size > 32 * 1024 * 1024:
            raise ValueError("host sample byte ceiling exhausted")
        with path.open("a") as stream:
            stream.write(json.dumps(snapshot, separators=(",", ":")) + "\n")
            stream.flush()
        self.last = time.monotonic()
        if bad:
            raise ValueError(
                "decisive timed games conflict with active compiler, data, training, arena or performance work"
            )


def configuration(rule, engine, network, openings, setting):
    rules = rule["matches"]
    options = {
        "Threads": rules["threads"],
        "Hash": rules["hash_mib"],
        "Ordering Hints": False,
        "Neural Bounds": False,
        "Evaluation Cache": rule["search_optimizations"]["evaluation_cache"],
        "Tactical Generation": rule["search_optimizations"]["tactical_generation"],
    }
    candidate = {
        "name": "Caissa validation-selected original model",
        "command": [str(engine)],
        "options": {
            **options,
            "EvalFile": str(network),
            "Use Neural": True,
            "Neural Weight": rule["network"]["neural_weight"],
        },
    }
    if setting is None:
        opponent = {
            "name": "Caissa unchanged classical contract1",
            "command": [str(engine)],
            "options": {**options, "Use Neural": False},
        }
        pairs = rules["neural_pairs"]
    else:
        index, stockfish = setting
        external = {"Threads": rules["threads"], "Hash": rules["hash_mib"]}
        if index == 0:
            external.update({"UCI_LimitStrength": False, "Skill Level": 0})
        elif index == 1:
            external.update({"UCI_LimitStrength": True, "UCI_Elo": 2000})
        elif index == 2:
            external.update({"UCI_LimitStrength": False, "Skill Level": 20})
        else:
            raise ValueError("external full setting is outside its frozen inventory")
        opponent = {
            "name": rules["external_settings"][index],
            "command": [str(stockfish)],
            "options": external,
        }
        pairs = rules["external_pairs"][index]
    return {
        "profile": "full fixed-sample original-engine strength",
        "candidate": candidate,
        "opponent": opponent,
        "pairs": pairs,
        "milliseconds": rules["milliseconds"],
        "warmup_nodes": rules["warmup_nodes"],
        "transport_allowance_ms": rules["transport_allowance_ms"],
        "max_plies": rules["maximum_plies"],
        "openings": str(openings),
    }


def validate_matches(rule):
    matches = rule["matches"]
    expected = {
        "milliseconds": 100,
        "threads": 1,
        "hash_mib": 16,
        "workers": 2,
        "warmup_nodes": 1,
        "transport_allowance_ms": 150,
        "maximum_plies": 512,
        "neural_pairs": 2000,
        "external_pairs": [334, 333, 333],
        "maximum_neural_campaign_wall_seconds": 43200,
        "maximum_external_campaign_wall_seconds": 43200,
    }
    if any(matches.get(key) != value for key, value in expected.items()):
        raise ValueError(
            "full matched resources, fixed samples or cumulative ceilings differ"
        )


def execute(args):
    root = Path.cwd().resolve()
    rule = frozen_rule(args.protocol, args.expected_protocol_sha256)
    validate_matches(rule)
    models = args.model_campaign.resolve()
    model_receipt = models / "MODEL_CAMPAIGN.json"
    if sha(model_receipt) != args.expected_model_campaign_sha256:
        raise ValueError(
            "full match model campaign differs from its external frozen identity"
        )
    model = read_json(model_receipt.read_text())
    engine, network = models / "bin/caissa", models / "selection/selected.cai"
    if (
        model["protocol_sha256"] != args.expected_protocol_sha256
        or model["seeds"] != [17, 41, 73]
        or model["updates_per_seed"] != 20000
        or model["test_model_metrics_used_for_selection"] is not False
        or model["engine_sha256"] != sha(engine)
        or model["network_sha256"] != sha(network)
        or model["checkpoint_sha256"] != sha(models / "selection/selected.pt")
        or model["dataset_sha256"] != rule["data"]["dataset_sha256"]
    ):
        raise ValueError(
            "full model provenance, selection or executable identity differs"
        )
    output = (
        root
        / "runs"
        / (
            "full-neural-strength-v3"
            if args.kind == "neural"
            else "full-external-strength-v3"
        )
    )
    if args.kind == "external" and (
        args.stockfish is None
        or sha(args.stockfish) != rule["matches"]["stockfish_sha256"]
    ):
        raise ValueError("external strength executable differs from pinned Stockfish19")
    if args.resume:
        inputs = read_json((output / "SOURCE_INPUTS.json").read_text())
        commit = inputs["commit"]
    else:
        if subprocess.check_output(["git", "status", "--porcelain"], text=True):
            raise ValueError(
                "commit strength owner and frozen settings before timed games"
            )
        commit = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], text=True
        ).strip()
        inputs = {
            "commit": commit,
            "files": {path: sha(root / path) for path in source_files(root)},
        }
    if sha(Path(__file__)) != inputs["files"]["tools/full_strength.py"]:
        raise ValueError("resume full strength with its original archived owner source")
    bindings = {
        "source_commit": commit,
        "protocol_sha256": args.expected_protocol_sha256,
        "model_campaign_sha256": args.expected_model_campaign_sha256,
        "engine_sha256": model["engine_sha256"],
        "network_sha256": model["network_sha256"],
        "kind": args.kind,
        "workflow_sha256": inputs["files"]["tools/full_strength.py"],
    }
    ceiling = rule["matches"]["maximum_" + args.kind + "_campaign_wall_seconds"]
    # Strength retains its separate prospectively frozen twelve-hour budget.
    power = PowerGuard(rule["model_campaign"]["host_policy"])
    scope = RecoveryScope(
        output,
        bindings,
        ceiling,
        models,
        10,
        20,
        resume=args.resume,
        maximum_authorized_seconds=43200,
    )
    campaign = None
    try:
        power.start(output)
        if not args.resume:
            atomic(output / "SOURCE_INPUTS.json", inputs)
            (output / "inputs").mkdir()
            shutil.copy2(args.protocol, output / "inputs/PROTOCOL.json")
            shutil.copy2(model_receipt, output / "inputs/MODEL_CAMPAIGN.json")
        attempts = sorted((output / "attempts").glob("attempt-*"))
        if len(attempts) >= 3:
            raise ValueError("full strength maximum three recovery attempts exhausted")
        source = output / "source"
        archive_source(root, source, commit, inputs["files"])
        openings = output / "inputs/OPENINGS.json"
        original_openings = source / rule["matches"]["opening_file"]
        if openings.exists():
            if sha(openings) != sha(original_openings):
                raise ValueError("strength opening bytes changed on resume")
        else:
            shutil.copy2(original_openings, openings)
        host = HostGuard(output, scope, power)
        atomic(
            output / ("HOST_START_" + str(len(attempts) + 1) + ".json"),
            {
                "platform": platform.platform(),
                "cpu_count": os.cpu_count(),
                "processes": process_rows(),
                "unix": time.time(),
            },
        )
        host.check()
        campaign = Campaign(
            output / "attempts" / f"attempt-{len(attempts)+1:03d}",
            bindings,
            scope.remaining(),
            absolute_deadline=scope.deadline,
            resource_guard=host.check,
        )

        def run(name, module, arguments):
            host.check()
            return campaign.run(
                name,
                [sys.executable, "-m", module, *map(str, arguments)],
                scope.remaining(),
                cwd=source,
            )

        schedule = (
            [("neural", None)]
            if args.kind == "neural"
            else [(f"external-{i}", (i, args.stockfish.resolve())) for i in range(3)]
        )
        roots = []
        for name, setting in schedule:
            directory = output / name
            roots.append(directory)
            config = output / "inputs" / (name + ".json")
            actual = configuration(rule, engine, network, openings, setting)
            if config.exists():
                if read_json(config.read_text()) != actual:
                    raise ValueError("strength actor configuration changed on resume")
            else:
                atomic(config, actual)
            run(
                "play-" + name,
                "arena.run",
                [config, directory, "--workers", rule["matches"]["workers"]],
            )
            run("statistics-" + name, "arena.statistics", [directory])
        failed = []
        if args.kind == "neural":
            try:
                run(
                    "independent-neural",
                    "verification.strength",
                    [
                        roots[0],
                        "--openings",
                        openings,
                        "--engine-sha256",
                        model["engine_sha256"],
                        "--network-sha256",
                        model["network_sha256"],
                        "--protocol",
                        output / "inputs/PROTOCOL.json",
                        "--neural",
                        "--require-full",
                    ],
                )
            except StageFailure as error:
                observed = read_json(
                    (campaign.output / "independent-neural.log").read_text()
                )
                if (
                    error.record["exit"] != 1
                    or observed.get("reason")
                    != "full neural contribution failed its predeclared Elo endpoint"
                    or observed.get("observed", {}).get("games", 0) < 4000
                ):
                    raise
                failed.append("G08 neural contribution failed its frozen endpoint")
        else:
            run(
                "independent-external",
                "verification.external_strength",
                [
                    *roots,
                    "--openings",
                    openings,
                    "--engine-sha256",
                    model["engine_sha256"],
                    "--network-sha256",
                    model["network_sha256"],
                    "--protocol",
                    output / "inputs/PROTOCOL.json",
                ],
            )
        result = {
            "status": (
                "completed fixed full strength sample"
                if not failed
                else "completed fixed full strength sample with failed gate"
            ),
            "failed_domains": failed,
            "source_commit": commit,
            "protocol_sha256": args.expected_protocol_sha256,
            "model_campaign_sha256": args.expected_model_campaign_sha256,
            "engine_sha256": model["engine_sha256"],
            "network_sha256": model["network_sha256"],
            "origin_unix": scope.state["origin_unix"],
            "deadline_unix": scope.deadline,
            "completed_unix": time.time(),
            "campaigns": [str(path.relative_to(output)) for path in roots],
            "absolute_elo": None,
            "full_acceptance": False,
        }
        atomic(output / "STRENGTH_CAMPAIGN.json", result)
        campaign.close(result["status"], result)
        print(json.dumps(result))
        return 2 if failed else 0
    except BaseException as error:
        if campaign is not None:
            campaign.close(
                "failed", {"type": type(error).__name__, "reason": str(error)}
            )
        atomic(
            output / "FAILED.json",
            {
                "reason": str(error),
                "type": type(error).__name__,
                "original_deadline_unix": scope.deadline,
                "observed_unix": time.time(),
                "full_acceptance": False,
            },
        )
        raise
    finally:
        try:
            power.close()
        finally:
            scope.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("kind", choices=["neural", "external"])
    parser.add_argument("--protocol", type=Path, required=True)
    parser.add_argument("--expected-protocol-sha256", required=True)
    parser.add_argument("--model-campaign", type=Path, required=True)
    parser.add_argument("--expected-model-campaign-sha256", required=True)
    parser.add_argument("--stockfish", type=Path)
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    try:
        return execute(args)
    except (
        ValueError,
        KeyError,
        OSError,
        RuntimeError,
        subprocess.SubprocessError,
    ) as error:
        print(
            json.dumps(
                {"status": "failed", "reason": str(error), "full_acceptance": False}
            )
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
