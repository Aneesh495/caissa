"""Capture finite original-native witnesses for the separate G14 audit."""

import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

from tools.host_lease import ENVIRONMENT, inherited
from verification.source import PRODUCT, snapshot
from verification.tactical_generation import Probe

PROFILE = "750a973a5a4d2f7d53238f204ef4b225d280854eb057d77900403f7d185d21ad"


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n")


def capture(engine, network, profile, output):
    from tools.heuristic_study import avoid_decisive_matches

    project = Path(__file__).resolve().parents[1]
    avoid_decisive_matches(project / "runs")
    if not inherited(project / "runs/TIMED_STRENGTH.lock"):
        raise ValueError(
            "G14 witness requires the actual inherited exclusive host lease"
        )
    engine, network, profile, output = map(
        lambda p: Path(p).resolve(), [engine, network, profile, output]
    )
    if output.exists() or sha(profile) != PROFILE:
        raise ValueError("G14 immutable output or prospective profile differs")
    rule = json.loads(profile.read_text())
    if sha(network) != rule["network_sha256"]:
        raise ValueError("G14 original selected network differs")
    output.mkdir(parents=True)
    started, active = time.time(), time.monotonic()
    deadline = started + 120
    source = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=project, text=True, timeout=5
    ).strip()
    for origin, name in [
        (engine, "engine"),
        (network, "network.cai"),
        (profile, "PROFILE.json"),
        (project / "config/protocol-v4.json", "V4.json"),
        (
            project / "results/full-model-v3-2026-10-25/MODEL_CAMPAIGN.json",
            "MODEL_CAMPAIGN.json",
        ),
    ]:
        shutil.copy2(origin, output / name)
    (output / "engine").chmod(0o755)
    write(
        output / "SOURCE_INPUTS.json",
        {
            "schema": "caissa-source-inputs-v2",
            "policy": PRODUCT,
            "commit": source,
            "files": snapshot(project, source, PRODUCT),
        },
    )
    write(
        output / "CONFIG.json",
        {
            "schema": "caissa-semantic-witness-v1",
            "source_commit": source,
            "engine_sha256": sha(engine),
            "network_sha256": sha(network),
            "profile_sha256": PROFILE,
            "started_unix": started,
            "deadline_unix": deadline,
            "maximum_seconds": 120,
            "full_acceptance": False,
        },
    )

    def remaining():
        if not inherited(project / "runs/TIMED_STRENGTH.lock"):
            raise ValueError("G14 inherited host ownership was lost")
        left = min(deadline - time.time(), 120 - (time.monotonic() - active))
        if left <= 0 or shutil.disk_usage(output).free < 10 * 1024**3:
            raise ValueError("G14 original producer time or free-space bound exhausted")
        if (
            sum(p.stat().st_size for p in output.rglob("*") if p.is_file())
            > 512 * 1024**2
        ):
            raise ValueError("G14 original output byte bound exhausted")
        return left

    def run(arguments):
        from tools.campaign_process import Campaign

        # The bounded controller owns and reaps the entire native process group.
        folder = output / ("process-" + str(len(list(output.glob("process-*")))))
        campaign = Campaign(
            folder,
            {"purpose": "G14 native witness", "source_commit": source},
            min(20, remaining()),
            resource_guard=remaining,
        )
        try:
            result = campaign.run(
                "native",
                arguments,
                min(15, remaining()),
                pass_fds=(int(os.environ[ENVIRONMENT]),),
                cwd=project,
                maximum_output_bytes=1048576,
            )
            observation = {
                "command": arguments,
                "exit": result["exit"],
                "stdout": (folder / "native.log").read_text(),
                "stderr": "",
            }
            with (output / "COMMANDS.jsonl").open("a") as stream:
                stream.write(json.dumps(observation) + "\n")
            if result["exit"]:
                raise ValueError("G14 native witness command failed")
            campaign.close("completed")
            return observation
        finally:
            if not campaign.closed:
                campaign.close("failed")

    witness = {"searches": [], "inference": [], "draws": []}
    for fen in rule["fens"]:
        observation = run([str(output / "engine"), "--search", "3", fen, "1"])
        witness["searches"].append(
            {"fen": fen, **{k: observation[k] for k in ["exit", "stdout", "stderr"]}}
        )
    probe = Probe(
        output / "engine", ["--net-probe", str(output / "network.cai"), "10"], deadline
    )
    try:
        for fen in rule["fens"]:
            remaining()
            probe.request(fen)
            witness["inference"].append(
                {
                    "fen": fen,
                    "exit": 0,
                    "stderr": "",
                    "stdout": probe.last_response.decode() + "\n",
                }
            )
    finally:
        probe.close()
    if probe.process.returncode or probe.stderr or probe.buffer:
        raise ValueError("G14 native network transport failed")
    probe = Probe(
        output / "engine", ["--state-probe", str(output / "network.cai")], deadline
    )
    try:
        for commands in rule["draw_histories"]:
            raw = []
            for command in commands:
                remaining()
                probe.request(command)
                raw.append(probe.last_response.decode())
            probe.request("rules")
            witness["draws"].append(
                {
                    "commands": commands,
                    "state_stdout": raw,
                    "rules_stdout": probe.last_response.decode(),
                }
            )
    finally:
        probe.close()
    if probe.process.returncode or probe.stderr or probe.buffer:
        raise ValueError("G14 native draw transport failed")
    write(output / "WITNESSES.json", witness)
    write(
        output / "OPENINGS.json",
        {
            "openings": [
                {"id": "g14-mate-" + str(i), "fen": fen, "moves": []}
                for i, fen in enumerate(rule["mate_fens"])
            ]
        },
    )
    actor = {
        "name": "Caissa G14 original diagnostic",
        "command": [str(output / "engine")],
        "options": {"Threads": 1, "Hash": 1, "Use Neural": False},
    }
    config = {
        "profile": "g14-semantic-witness-only",
        "candidate": actor,
        "opponent": {**actor, "name": "Caissa G14 reversed diagnostic"},
        "openings": str(output / "OPENINGS.json"),
        "pairs": 2,
        "nodes": 1000,
        "max_plies": 64,
        "warmup_nodes": 1,
    }
    write(output / "ARENA_INPUT.json", config)
    run(
        [
            sys.executable,
            "-B",
            "-m",
            "arena.run",
            str(output / "ARENA_INPUT.json"),
            str(output / "arena"),
            "--workers",
            "1",
        ]
    )
    remaining()
    # Process controller logs are retained outside the immutable compact witness.
    # They are transported separately by the new audit development workflow.
    for folder in output.glob("process-*"):
        shutil.move(str(folder), output.parent / (output.name + "-" + folder.name))
    files = {
        str(p.relative_to(output)): sha(p)
        for p in sorted(output.rglob("*"))
        if p.is_file()
    }
    write(output / "MANIFEST.json", {"files": files})
    return {
        "source_commit": source,
        "engine_sha256": sha(engine),
        "network_sha256": sha(network),
        "manifest_sha256": sha(output / "MANIFEST.json"),
        "elapsed_seconds": time.monotonic() - active,
        "strength_games": 0,
        "diagnostic_games": 4,
        "full_acceptance": False,
    }
