"""Real Git fixtures distinguish committed source from rehashed edited files."""

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from verification.source import LEGACY, PRODUCT, snapshot, verify_checkout


def repository(root):
    root.mkdir()
    files = {
        "CMakeLists.txt": "project(fixture)\n",
        "src/main.cpp": "int main(){return 0;}\n",
        "include/core.h": "void fixture();\n",
        "web/index.html": "<title>fixture</title>\n",
        "web/style.css": "body {color:black}\n",
        "tests/flow.mjs": "export const fixture = true;\n",
    }
    for name, value in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(value)
    for command in [
        ["git", "init", "-q"],
        ["git", "add", "."],
        [
            "git",
            "-c",
            "user.name=fixture",
            "-c",
            "user.email=fixture@invalid",
            "commit",
            "-qm",
            "fixture",
        ],
    ]:
        subprocess.run(command, cwd=root, check=True, capture_output=True, timeout=5)
    return subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=root, text=True, timeout=5
    ).strip()


def source_document(root, commit):
    return {
        "schema": "caissa-source-inputs-v2",
        "policy": PRODUCT,
        "commit": commit,
        "files": snapshot(root, commit, PRODUCT),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    project = Path(__file__).resolve().parents[1]
    results = []
    with tempfile.TemporaryDirectory(prefix="caissa-source-controls-") as temporary:
        root = Path(temporary) / "source"
        commit = repository(root)
        original = source_document(root, commit)
        legacy = snapshot(root, commit, LEGACY)
        assert set(legacy) == {"CMakeLists.txt", "src/main.cpp"}
        assert {
            "include/core.h",
            "web/index.html",
            "web/style.css",
            "tests/flow.mjs",
        } <= set(original["files"])
        verify_checkout(root, {"commit": commit, "files": legacy}, commit, LEGACY)
        manifest = Path(temporary) / "SOURCE_INPUTS.json"
        env = dict(os.environ, PYTHONPATH=str(project))
        for case in [
            "unchanged",
            "edited-native-rehashed",
            "edited-browser-rehashed",
            "edited-native-unrehashed",
            "edited-browser-unrehashed",
            "omitted-asset",
            "linked-source",
            "wrong-commit",
        ]:
            value = json.loads(json.dumps(original))
            changed = None
            target = None
            if case.startswith("edited-"):
                name = "src/main.cpp" if "native" in case else "web/index.html"
                changed = root / name
                saved = changed.read_bytes()
                changed.write_bytes(saved + b"changed\n")
                if not case.endswith("unrehashed"):
                    value["files"][name] = hashlib.sha256(
                        changed.read_bytes()
                    ).hexdigest()
            elif case == "omitted-asset":
                del value["files"]["web/style.css"]
            elif case == "linked-source":
                changed = root / "src/main.cpp"
                saved = changed.read_bytes()
                target = Path(temporary) / "outside.cpp"
                target.write_bytes(saved)
                changed.unlink()
                changed.symlink_to(target)
            elif case == "wrong-commit":
                value["commit"] = "0" * 40
            manifest.write_text(json.dumps(value) + "\n")
            command = [
                sys.executable,
                "-m",
                "verification.source",
                str(manifest),
                "--checkout",
                str(root),
                "--expected-commit",
                commit,
            ]
            run = subprocess.run(
                command,
                cwd=temporary,
                env=env,
                capture_output=True,
                text=True,
                timeout=15,
            )
            result = json.loads(run.stdout)
            assert run.returncode == (0 if case == "unchanged" else 1), (
                case,
                run.stdout,
                run.stderr,
            )
            if case != "unchanged":
                assert result["status"] == "rejected" and result["reason"]
            results.append(
                {
                    "case": case,
                    "command": command,
                    "exit": run.returncode,
                    "observed": result,
                    "stderr": run.stderr,
                    "ordinary_hashes_recomputed": case.endswith("-rehashed"),
                }
            )
            if changed is not None:
                if changed.is_symlink():
                    changed.unlink()
                changed.write_bytes(saved)
        assert snapshot(root, commit, LEGACY) == legacy
    report = {
        "status": "passed",
        "cases": results,
        "legacy_policy_preserved": True,
        "scope": "Source identity controls on a synthetic Git fixture; no engine or model execution",
        "full_acceptance": False,
    }
    (args.output / "CONTROLS.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report))


if __name__ == "__main__":
    main()
