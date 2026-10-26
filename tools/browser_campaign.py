"""A finite real-browser campaign, excluded from decisive local games."""

import argparse
import hashlib
import json
import shutil
import subprocess
import time
from pathlib import Path

from tools.campaign_process import Campaign, atomic
from tools.heuristic_study import avoid_decisive_matches
from tools.host_lease import HostLease
from tools.recovery_scope import tree_bytes


def execute(engine, network, output):
    avoid_decisive_matches()
    engine, network, output = (Path(p).resolve() for p in [engine, network, output])
    if output.exists():
        raise ValueError("browser evidence already exists; preserve it")
    lease = HostLease(Path("runs"))
    campaign = None
    try:
        wall = time.time()
        config = {
            "schema": "caissa-browser-campaign-v1",
            "profile": "browser-component-only",
            "source_commit": subprocess.check_output(
                ["git", "rev-parse", "HEAD"], text=True, timeout=5
            ).strip(),
            "engine": str(engine),
            "network": str(network),
            "engine_sha256": hashlib.sha256(engine.read_bytes()).hexdigest(),
            "network_sha256": hashlib.sha256(network.read_bytes()).hexdigest(),
            "maximum_seconds": 240,
            "maximum_additional_bytes": 256 * 1024**2,
            "minimum_free_bytes": 10 * 1024**3,
            "started_unix": wall,
            "deadline_unix": wall + 240,
            "viewports": [1280, 390],
            "modes": ["classical", "neural"],
            "neural_weight": 10,
            "classical_contract": 1,
            "lazy_neural": True,
            "playwright": "1.56.1",
            "full_G12_certified": False,
        }

        def guard():
            lease.check()
            if shutil.disk_usage(output).free < config["minimum_free_bytes"]:
                raise ValueError("browser free-space reserve exhausted")
            if tree_bytes(output) > config["maximum_additional_bytes"]:
                raise ValueError("browser additional output ceiling exhausted")

        campaign = Campaign(output, config, 240, resource_guard=guard)
        campaign.run(
            "browser",
            ["node", "tools/browser_campaign.mjs", str(output)],
            235,
            maximum_output_bytes=1024 * 1024,
            env=lease.environment(),
            pass_fds=(lease.stream.fileno(),),
        )
        for path, key in [(engine, "engine_sha256"), (network, "network_sha256")]:
            if hashlib.sha256(path.read_bytes()).hexdigest() != config[key]:
                raise ValueError("browser native input changed during execution")
        campaign.close("recorded", {"full_G12_certified": False})
        atomic(
            output / "MANIFEST.json",
            {
                "files": {
                    str(p.relative_to(output)): hashlib.sha256(
                        p.read_bytes()
                    ).hexdigest()
                    for p in sorted(output.rglob("*"))
                    if p.is_file() and p.name != "MANIFEST.json"
                }
            },
        )
        return config
    except BaseException as error:
        if campaign is not None:
            campaign.close("failed", {"reason": str(error)})
        raise
    finally:
        lease.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--engine", type=Path, required=True)
    parser.add_argument("--network", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    execute(args.engine, args.network, args.output)
    print(json.dumps({"status": "recorded", "full_G12_certified": False}))


if __name__ == "__main__":
    main()
