"""Real killed arena writer plus rehashed semantic forgeries through its CLI."""

import argparse
import copy
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from tools.campaign_process import atomic
from verification.bundle import Bundle
from verification.recovery_bundle import verify_arena


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--engine", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    root = args.output / "positive"
    producer = subprocess.run(
        [
            sys.executable,
            "-m",
            "tools.arena_recovery",
            "--engine",
            str(args.engine),
            "--output",
            str(root),
        ],
        capture_output=True,
        text=True,
        timeout=130,
    )
    (args.output / "producer.log").write_text(producer.stdout + producer.stderr)
    assert producer.returncode == 0, producer.stdout + producer.stderr
    config = json.loads((root / "CONFIG.json").read_text())
    controls = []

    def run(case, folder, reason=None):
        command = [
            sys.executable,
            "-m",
            "verification.arena_recovery",
            str(folder),
            "--engine-sha256",
            config["engine_sha256"],
            "--source-commit",
            config["source_commit"],
            "--maximum-seconds",
            "30",
        ]
        if reason is None:
            command += ["--native-output", str(args.output / (case + "-native"))]
        actual = subprocess.run(command, capture_output=True, text=True, timeout=35)
        (args.output / (case + ".log")).write_text(actual.stdout + actual.stderr)
        value = json.loads(actual.stdout)
        if reason is None:
            assert (
                actual.returncode == 0
                and value["component_pass"] is True
                and value["full_G11_certified"] is False
            ), value
            assert (
                value["actual_forced_exit"] == -9 and value["reconstructed_games"] == 4
            )
        else:
            assert actual.returncode == 1 and reason in value["reason"], (case, value)
        controls.append(
            {"case": case, "actual_exit": actual.returncode, "observed": value}
        )

    run("actual-interruption-and-replay", root)
    # A valid manifest is necessary, but still cannot certify full G11.
    with tempfile.TemporaryDirectory(prefix="caissa-recovery-bundle-") as temporary:
        evidence = Path(temporary) / "evidence"
        shutil.copytree(root, evidence / "arena-component")
        files = {
            str(p.relative_to(evidence)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in evidence.rglob("*")
            if p.is_file()
        }
        atomic(evidence / "MANIFEST.json", {"files": files})
        refs = [{"artifact": name, "sha256": digest} for name, digest in files.items()]
        config_ref = next(
            ref for ref in refs if ref["artifact"] == "arena-component/CONFIG.json"
        )
        inputs = {
            "engine": {"sha256": config["engine_sha256"]},
            "domains": {
                "G11": {
                    "source_commit": config["source_commit"],
                    "arena_recovery": {"config": config_ref},
                    "artifacts": refs,
                }
            },
        }
        with Bundle(evidence, 60) as bundle:
            bundle.verify_manifest()
            value = verify_arena(bundle, inputs, Path(temporary) / "replay")
            assert (
                value["component_pass"] is True and value["full_G11_certified"] is False
            )
        controls.append(
            {"case": "actual-bundle-staging-and-replay", "full_G11_certified": False}
        )
    cases = {
        "fake-kill": "actual forced SIGKILL",
        "boolean-signal": "actual forced SIGKILL",
        "changed-protected-game": "protected committed game",
        "changed-boundary": "boundary identity",
        "extended-deadline": "original resource bounds",
        "missing-pgn": "raw inventory",
        "extra-game": "raw inventory",
        "missing-torn-write": "raw inventory",
        "wrong-engine": "source/program identity",
        "changed-control": "control or program",
        "illegal-pv": "principal variation is illegal",
    }
    for case, reason in cases.items():
        folder = args.output / case
        shutil.copytree(root, folder)
        if case in {"fake-kill", "boolean-signal"}:
            path = folder / "KILL.json"
            value = json.loads(path.read_text())
            value["actual_exit" if case == "fake-kill" else "signal"] = (
                0 if case == "fake-kill" else True
            )
            atomic(path, value)
        elif case == "changed-protected-game":
            path = folder / "arena/games/000000-0.json"
            value = json.loads(path.read_text())
            value["result"] = "0-1"
            atomic(path, value)
        elif case == "changed-boundary":
            path = folder / "arena/RECOVERY_READY.json"
            value = json.loads(path.read_text())
            value["pair"] = True
            atomic(path, value)
        elif case in {"extended-deadline", "wrong-engine"}:
            path = folder / "CONFIG.json"
            value = json.loads(path.read_text())
            if case == "extended-deadline":
                value["maximum_seconds"] = 121
                value["deadline_unix"] += 1
            else:
                value["engine_sha256"] = "a" * 64
            atomic(path, value)
        elif case == "missing-pgn":
            (folder / "arena/games/000000-0.pgn").unlink()
        elif case == "extra-game":
            shutil.copyfile(
                folder / "arena/games/000000-0.json",
                folder / "arena/games/999999-0.json",
            )
        elif case == "missing-torn-write":
            (folder / "partial-before/000000-0.pgn.tmp").unlink()
        elif case == "changed-control":
            path = folder / "arena/CONFIG.json"
            value = json.loads(path.read_text())
            value["executables"]["opponent"]["options"]["Hash"] = 2
            value["config"]["opponent"]["options"]["Hash"] = 2
            atomic(path, value)
            atomic(folder / "ARENA_INPUT.json", value["config"])
        elif case == "illegal-pv":
            path = folder / "arena/games/000000-1.json"
            value = json.loads(path.read_text())
            observation = next(x for x in value["observations"] if "uci" in x)
            observation["uci"].insert(0, "info depth 1 score cp 0 pv a1a8")
            atomic(path, value)
            pair_path = folder / "arena/pairs/000000.json"
            pair = json.loads(pair_path.read_text())
            pair["games"][1] = value
            atomic(pair_path, pair)
        run(case, folder, reason)
    # Strength profiles cannot activate the fault-injection branch.
    candidate = json.loads((root / "ARENA_INPUT.json").read_text())
    candidate["profile"] = "full fixed-sample original-engine strength"
    atomic(args.output / "rejected-strength-config.json", candidate)
    forbidden = subprocess.run(
        [
            sys.executable,
            "-m",
            "arena.run",
            str(args.output / "rejected-strength-config.json"),
            str(args.output / "forbidden-output"),
            "--workers",
            "1",
            "--recovery-barrier",
            str(args.output / "forbidden-output/READY.json"),
        ],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert (
        forbidden.returncode == 1
        and "restricted to its isolated diagnostic" in forbidden.stderr
    )
    assert not (args.output / "forbidden-output").exists()
    controls.append(
        {
            "case": "strength-profile-cannot-use-recovery-failpoint",
            "actual_exit": forbidden.returncode,
        }
    )
    atomic(
        args.output / "CONTROLS.json",
        {
            "status": "passed",
            "cases": controls,
            "actual_forced_exit": -9,
            "positive_reconstructed_games": 4,
            "training_and_data_recovery_still_required": True,
            "full_G11_certified": False,
            "full_acceptance": False,
        },
    )
    print(
        json.dumps(
            {
                "status": "passed",
                "cases": len(controls),
                "actual_forced_exit": -9,
                "positive_reconstructed_games": 4,
                "full_G11_certified": False,
                "full_acceptance": False,
            }
        )
    )


if __name__ == "__main__":
    main()
