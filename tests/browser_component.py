"""Real browser/native campaign and rehashed semantic rejection controls."""

import argparse
import copy
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from tests.full_bundle import reference
from tools.campaign_process import atomic
from verification.browser_bundle import verify as replay_bundle
from verification.bundle import Bundle


def seal(root):
    atomic(
        root / "MANIFEST.json",
        {
            "files": {
                str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in sorted(root.rglob("*"))
                if p.is_file() and p.name != "MANIFEST.json"
            }
        },
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--engine", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    root = args.output / "positive"
    actual = subprocess.run(
        [
            sys.executable,
            "-m",
            "tools.browser_campaign",
            "--engine",
            str(args.engine),
            "--network",
            "results/precision-v4-2026-10-25/selected-v4.cai",
            "--output",
            str(root),
        ],
        capture_output=True,
        text=True,
        timeout=250,
    )
    (args.output / "producer.log").write_text(actual.stdout + actual.stderr)
    assert actual.returncode == 0, (
        actual.stdout
        + actual.stderr
        + (
            (root / "browser-process.log").read_text()
            if (root / "browser-process.log").exists()
            else ""
        )
    )
    config = json.loads((root / "CONFIG.json").read_text())
    results = []

    def run(label, folder, reason=None):
        command = [
            sys.executable,
            "-m",
            "verification.browser",
            str(folder),
            "--engine-sha256",
            config["engine_sha256"],
            "--network-sha256",
            config["network_sha256"],
            "--source-commit",
            config["source_commit"],
        ]
        actual = subprocess.run(command, capture_output=True, text=True, timeout=65)
        (args.output / (label + ".log")).write_text(actual.stdout + actual.stderr)
        value = json.loads(actual.stdout)
        if reason is None:
            assert (
                actual.returncode == 0
                and value["component_pass"] is True
                and value["full_G12_certified"] is False
            ), value
        else:
            assert actual.returncode == 1 and reason in value["reason"], (label, value)
        results.append(
            {"case": label, "actual_exit": actual.returncode, "observed": value}
        )

    run("real-browser-reconstruction", root)
    with tempfile.TemporaryDirectory(prefix="caissa-browser-staging-") as temporary:
        temporary = Path(temporary)
        evidence = temporary / "evidence"
        shutil.copytree(root, evidence / "browser")
        identities = {
            str(p.relative_to(evidence)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in evidence.rglob("*")
            if p.is_file()
        }
        atomic(evidence / "MANIFEST.json", {"files": identities})
        inputs = {
            "engine": {"sha256": config["engine_sha256"]},
            "network": {"artifact": {"sha256": config["network_sha256"]}},
            "domains": {
                "G12": {
                    "source_commit": config["source_commit"],
                    "browser": {"config": reference(evidence, "browser/CONFIG.json")},
                    "artifacts": [
                        {"path": path, "sha256": digest}
                        for path, digest in identities.items()
                    ],
                }
            },
        }
        with Bundle(evidence, 60) as bundle:
            bundle.verify_manifest()
            value = replay_bundle(bundle, inputs, temporary / "replay")
            assert (
                value["component_pass"] is True and value["full_G12_certified"] is False
            )
        results.append({"case": "immutable-bundle-stage", "observed": value})
    cases = [
        ("saved-pass-without-raw", "BROWSER.json", "sample"),
        ("wrong-board-piece", "BROWSER.json", "rendered board"),
        ("keyboard-focus-lost", "BROWSER.json", "keyboard destination"),
        ("stale-search-counters", "BROWSER.json", "stale analysis"),
        ("edited-variation-lost", "BROWSER.json", "export lost"),
        ("unreaped-native-worker", "BROWSER.json", "reap workers"),
        ("viewport-overflow", "BROWSER.json", "viewport overflowed"),
        ("stale-session-accepted", "BROWSER.json", "stale session"),
        ("illegal-native-pv", "NETWORK.json", "principal variation"),
        (
            "completed-native-stream-omitted",
            "NETWORK.json",
            "completed original native analysis",
        ),
        ("neural-not-used", "NETWORK.json", "evaluator was not actually used"),
        ("changed-mixture", "CONFIG.json", "evaluator or component"),
        ("promoted-full-gate", "CONFIG.json", "evaluator or component"),
        ("faked-visible-pv", "BROWSER.json", "displayed principal variations"),
        ("empty-trace", "classical-1280/trace.zip", "trace context"),
    ]
    for label, name, reason in cases:
        with tempfile.TemporaryDirectory(prefix="caissa-browser-forgery-") as temporary:
            folder = Path(temporary) / "raw"
            shutil.copytree(root, folder)
            if label == "empty-trace":
                import zipfile

                with zipfile.ZipFile(folder / name, "w") as archive:
                    archive.writestr("trace.trace", "")
                    archive.writestr("trace.network", "")
                seal(folder)
                run(label, folder, reason)
                continue
            value = json.loads((folder / name).read_text())
            if label == "saved-pass-without-raw":
                value["records"] = []
                value["status"] = "passed"
            elif label == "wrong-board-piece":
                value["records"][0]["cells"][0]["label"] = "a8 white queen"
            elif label == "keyboard-focus-lost":
                next(r for r in value["records"] if r["name"] == "keyboard-edit")[
                    "focus"
                ] = None
            elif label == "stale-search-counters":
                next(r for r in value["records"] if r["name"] == "position-change")[
                    "nodes"
                ] = "999"
            elif label == "edited-variation-lost":
                next(r for r in value["records"] if r["name"] == "export")[
                    "pgn"
                ] = "1. c4 *"
            elif label == "unreaped-native-worker":
                next(r for r in value["records"] if r["name"] == "cancel-reaped")[
                    "health"
                ]["analyses"] = 1
            elif label == "viewport-overflow":
                value["records"][0]["scrollWidth"] = 1400
            elif label == "stale-session-accepted":
                next(r for r in value["records"] if r["name"] == "stale-session")[
                    "status"
                ] = 200
            elif label == "changed-mixture":
                value["neural_weight"] = 20
            elif label == "promoted-full-gate":
                value["full_G12_certified"] = True
            elif label == "faked-visible-pv":
                next(r for r in value["records"] if r["name"] == "analysis")[
                    "lines"
                ] = ["1. a1a8"]
            elif label == "completed-native-stream-omitted":
                for row in value:
                    if row["url"] == "/api/analyze":
                        row.pop("body", None)
                        row["aborted"] = True
            else:
                changed = False
                for row in value:
                    if row["url"] != "/api/analyze" or "event: bestmove" not in row.get(
                        "body", ""
                    ):
                        continue
                    if label == "neural-not-used" and row["mode"] != "neural":
                        continue
                    frames = row["body"].strip().split("\n\n")
                    for i, frame in enumerate(frames):
                        event, data = frame.splitlines()
                        payload = json.loads(data[6:])
                        if label == "illegal-native-pv" and event == "event: info":
                            payload["pv"] = ["a1a8"]
                            changed = True
                        if label == "neural-not-used" and event == "event: statistics":
                            payload["neural_evaluations"] = 0
                            changed = True
                        frames[i] = event + "\n" + "data: " + json.dumps(payload)
                    row["body"] = "\n\n".join(frames) + "\n\n"
                assert changed
            atomic(folder / name, value)
            seal(folder)
            run(label, folder, reason)
    atomic(
        args.output / "CONTROLS.json",
        {"status": "passed", "controls": results, "full_G12_certified": False},
    )
    print(
        json.dumps(
            {
                "status": "passed",
                "cases": len(results),
                "real_contexts": 4,
                "full_G12_certified": False,
            }
        )
    )


if __name__ == "__main__":
    main()
