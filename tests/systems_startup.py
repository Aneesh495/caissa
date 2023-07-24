"""Check the real saved actor's model-loading order without playing games."""

import hashlib
import json
import time
from pathlib import Path

from arena.client import UciClient
from tools.systems_strength import configuration
from verification.systems_strength import contract


def main():
    root = Path.cwd()
    frozen = root / "runs/full-parallel-strength-v1"
    rule, base, _ = contract(
        frozen / "inputs/PROFILE.json", frozen / "inputs/BASE_PROTOCOL.json"
    )
    engine = frozen / "bin/caissa"
    network = frozen / "inputs/selected.cai"
    for path, key in [(engine, "engine_sha256"), (network, "network_sha256")]:
        assert (
            hashlib.sha256(path.read_bytes()).hexdigest() == base["strength_actor"][key]
        )
    start = time.monotonic()
    probes = 0
    for row in rule["comparisons"]:
        config = configuration(
            rule, row, engine, network, frozen / "inputs/OPENINGS.json"
        )
        for role in ["candidate", "opponent"]:
            assert time.monotonic() - start < 20
            actor = config[role]
            names = list(actor["options"])
            assert names.index("EvalFile") < names.index("Use Neural")
            with UciClient(actor["command"], actor["options"], timeout=1) as client:
                sent = client.configuration_commands
                assert next(
                    i
                    for i, s in enumerate(sent)
                    if s.startswith("setoption name EvalFile ")
                ) < sent.index("setoption name Use Neural value true")
                assert client.process.poll() is None
            probes += 1
    print(
        json.dumps(
            {
                "status": "passed",
                "saved_actor_handshakes": probes,
                "strength_games": 0,
                "seconds": time.monotonic() - start,
            }
        )
    )


if __name__ == "__main__":
    main()
