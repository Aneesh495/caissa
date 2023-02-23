"""Real small-arena staging and rejection of forged full-sample receipts."""

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from tests.full_bundle import fixture, reference, seal, sha, write
from tests.source_binding import repository
from verification.bundle import Bundle
from verification.match_journals import verify as journals
from verification.strength_bundle import stage_campaign
from verification.verify import independent_statistics


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--campaign", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    project = Path(__file__).resolve().parents[1]
    controls = []
    original_pairs = sorted((args.campaign / "pairs").glob("*.json"))
    assert len(original_pairs) == 2
    with tempfile.TemporaryDirectory(prefix="caissa-strength-bundle-") as temporary:
        temporary = Path(temporary)
        for case in [
            "actual-four-game-staging",
            "missing-game",
            "extra-pair",
            "undeclared-pgn",
            "boolean-pairs",
            "changed-after-hash",
            "linked-game",
            "weakened-full-count",
        ]:
            root = temporary / case
            shutil.copytree(args.campaign, root / "raw")
            config = root / "raw/CONFIG.json"
            if case == "missing-game":
                (root / "raw/games/000000-0.json").unlink()
            elif case == "extra-pair":
                shutil.copy2(
                    root / "raw/pairs/000000.json", root / "raw/pairs/999999.json"
                )
            elif case == "boolean-pairs":
                value = json.loads(config.read_text())
                value["config"]["pairs"] = True
                write(config, value)
            elif case == "linked-game":
                path = root / "raw/games/000000-0.json"
                outside = temporary / "outside-game.json"
                shutil.move(str(path), outside)
                path.symlink_to(outside)
            write(
                root / "MANIFEST.json",
                {
                    "files": {
                        str(p.relative_to(root)): sha(p)
                        for p in root.rglob("*")
                        if p.is_file()
                    }
                },
            )
            reason = None
            try:
                with Bundle(root, 30) as bundle:
                    bundle.verify_manifest()
                    declared = set(bundle.identities)
                    if case == "undeclared-pgn":
                        declared.remove("raw/games/000000-0.pgn")
                    elif case == "changed-after-hash":
                        path = root / "raw/pairs/000000.json"
                        path.write_bytes(path.read_bytes() + b" \n")
                    staged = stage_campaign(
                        bundle,
                        {"config": reference(root, "raw/CONFIG.json")},
                        declared,
                        temporary / (case + "-staged"),
                        2000 if case == "weakened-full-count" else 2,
                    )
                    result = journals(staged, maximum_seconds=30, tick=bundle.tick)
                    assert result["game_journals"] == 4
                    assert result["full_strength_sample_certified"] is False
            except ValueError as error:
                reason = str(error)
            expected = {
                "missing-game": "inventory",
                "extra-pair": "inventory",
                "undeclared-pgn": "inventory",
                "boolean-pairs": "fixed sample",
                "changed-after-hash": "changed after manifest",
                "linked-game": "symbolic link",
                "weakened-full-count": "fixed sample",
            }.get(case)
            assert (
                reason is None if expected is None else reason and expected in reason
            ), (case, reason)
            controls.append({"case": case, "reason": reason, "full_acceptance": False})

        # Reach the real full CLI with genuine four-game journals and a rehashed
        # "passed" receipt. The 4000-game floor must still reject them.
        source = temporary / "source"
        commit = repository(source)
        root = temporary / "full"
        inputs = fixture(root, project, source, commit)
        shutil.copytree(args.campaign, root / "matches/neural")
        domain = inputs["domains"]["G08"]
        domain["driver"] = "strength-journals-v1"
        domain["strength"] = {
            "campaigns": [{"config": reference(root, "matches/neural/CONFIG.json")}]
        }
        domain["artifacts"] = [
            reference(root, str(p.relative_to(root)))
            for p in sorted((root / "matches/neural").rglob("*"))
            if p.is_file()
        ]
        pin = seal(root, inputs)
        argv = [
            sys.executable,
            "-m",
            "verification.verify",
            str(root),
            "--checkout",
            str(source),
            "--expected-commit",
            commit,
            "--expected-inputs-sha256",
            pin,
            "--profile",
            "full",
            "--replay-output",
            str(temporary / "full-replay"),
        ]
        run = subprocess.run(
            argv,
            cwd=temporary,
            env=dict(os.environ, PYTHONPATH=str(project)),
            capture_output=True,
            text=True,
            timeout=30,
        )
        (args.output / "forged-full-receipt.log").write_text(run.stdout + run.stderr)
        actual = json.loads(run.stdout)
        assert run.returncode == 1 and "full fixed sample" in actual["reason"], actual
        controls.append(
            {
                "case": "forged-full-receipt",
                "command": argv,
                "actual_exit": run.returncode,
                "observed": actual,
            }
        )

        # A caller's original cumulative deadline must also interrupt bootstrap
        # work after records have been parsed. No scientific result is returned.
        ticks = 0

        def expired():
            nonlocal ticks
            ticks += 1
            if ticks == 4:
                raise ValueError("original cumulative deadline exhausted")

        try:
            independent_statistics(
                (json.loads(p.read_text()) for p in original_pairs), tick=expired
            )
        except ValueError as error:
            assert str(error) == "original cumulative deadline exhausted" and ticks == 4
        else:
            raise AssertionError("bootstrap ignored the caller deadline")
        controls.append({"case": "cumulative-bootstrap-deadline", "ticks": ticks})
    write(
        args.output / "CONTROLS.json",
        {
            "status": "passed",
            "controls": controls,
            "actual_small_sample_games": 4,
            "full_strength_sample_certified": False,
            "full_acceptance": False,
        },
    )
    print(
        json.dumps(
            {
                "status": "passed",
                "controls": len(controls),
                "full_strength_sample_certified": False,
                "full_acceptance": False,
            }
        )
    )


if __name__ == "__main__":
    main()
