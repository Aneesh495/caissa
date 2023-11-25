"""Amended capture verification with immutable evidence from the failed run."""

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import time
import zipfile
from pathlib import Path

from tools.recovery_join_inputs import download


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--engine", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    rule = json.loads(Path("config/browser-capture-amendment-v1.json").read_text())
    started = time.monotonic()

    def tick():
        if time.monotonic() - started >= 480 or time.time() >= rule["deadline_unix"]:
            raise ValueError("amended browser verification deadline exhausted")
        if shutil.disk_usage(args.output).free < rule["minimum_free_bytes"]:
            raise ValueError("amended browser verification reserve exhausted")
        if (
            sum(p.stat().st_size for p in args.output.rglob("*") if p.is_file())
            > rule["maximum_output_bytes_per_platform"]
        ):
            raise ValueError("amended browser verification output ceiling exhausted")

    def write(name, value):
        (args.output / name).write_text(json.dumps(value, indent=2) + "\n")

    receipt = {
        "status": "failed",
        "full_G12_certified": False,
        "old_failures_preserved": True,
        "new_strength_games": 0,
    }
    try:
        tick()
        engine_sha = hashlib.sha256(args.engine.read_bytes()).hexdigest()
        if sys.platform == "darwin" and engine_sha != rule["saved_engine_sha256"]:
            raise ValueError(
                "amended macOS browser verification requires the saved image"
            )
        network = Path("results/precision-v4-2026-10-25/selected-v4.cai")
        if hashlib.sha256(network.read_bytes()).hexdigest() != rule["network_sha256"]:
            raise ValueError("amended browser verification network identity differs")
        receipt["engine_sha256"] = engine_sha
        receipt["saved_image"] = engine_sha == rule["saved_engine_sha256"]
        archive = args.output / "original-failed-macos.zip"
        origin = download(rule["original_failed_artifact"], archive, tick)
        with zipfile.ZipFile(archive) as bundle:
            candidates = [
                info
                for info in bundle.infolist()
                if info.filename.endswith("positive/NETWORK.json")
            ]
            if len(candidates) != 1 or candidates[0].file_size > 32 * 1024**2:
                raise ValueError(
                    "original failed browser network member is ambiguous or excessive"
                )
            raw = bundle.read(candidates[0])
        rows = json.loads(raw)
        contexts = []
        for mode in ["classical", "neural"]:
            for width in [1280, 390]:
                analyses = [
                    r
                    for r in rows
                    if r["mode"] == mode
                    and r["width"] == width
                    and r["url"] == "/api/analyze"
                ]
                contexts.append(
                    {
                        "mode": mode,
                        "width": width,
                        "analysis_responses": len(analyses),
                        "aborted_captures": sum(
                            r.get("aborted") is True for r in analyses
                        ),
                        "complete_bestmove_bodies": sum(
                            "event: bestmove" in r.get("body", "") for r in analyses
                        ),
                    }
                )
        write(
            "ORIGINAL_CAPTURE_INSPECTION.json",
            {
                "schema": "caissa-failed-browser-capture-inspection-v1",
                "archive": origin,
                "member": candidates[0].filename,
                "member_sha256": hashlib.sha256(raw).hexdigest(),
                "member_bytes": len(raw),
                "contexts": contexts,
                "derived_metadata_only": True,
                "original_zip_unchanged": True,
                "cause": "Original observations are separate from the proposed UI transport-lifetime explanation.",
            },
        )
        tick()
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "tests.browser_component",
                "--engine",
                str(args.engine),
                "--output",
                str(args.output / "component"),
            ],
            capture_output=True,
            text=True,
            timeout=min(360, rule["deadline_unix"] - time.time()),
        )
        (args.output / "component.log").write_text(result.stdout + result.stderr)
        if result.returncode:
            raise ValueError(
                "actual amended browser component failed; see retained component.log"
            )
        tick()
        controls = json.loads((args.output / "component/CONTROLS.json").read_text())
        if (
            controls["status"] != "passed"
            or controls["full_G12_certified"] is not False
        ):
            raise ValueError("amended browser component receipt is inconsistent")
        receipt.update(
            status="passed",
            controls=len(controls["controls"]),
            real_contexts=4,
            final_all_domain_source_join_pending=True,
        )
    except BaseException as error:
        receipt["reason"] = str(error)
        raise
    finally:
        receipt["seconds"] = time.monotonic() - started
        write("RESULT.json", receipt)
    print(json.dumps(receipt))


if __name__ == "__main__":
    main()
