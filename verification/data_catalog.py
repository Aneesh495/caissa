"""Bounded original-data reconstruction from externally pinned input views.

Each view hashes only its declared inputs. It never writes a manifest into the
original corpus or pretends that unused preparation indexes were verified.
Staging and the independent reconstruction have distinct explicit ceilings.
"""

import argparse
import contextlib
import hashlib
import json
import re
import subprocess
import sys
import time
from pathlib import Path

from tools.campaign_process import Campaign, StageFailure, atomic
from tools.power_guard import POLICY, PowerGuard
from tools.recovery_scope import RecoveryScope
from verification.bundle import Bundle, digest_text, strict_json
from verification.source import (
    PRODUCT,
    relative_path,
    require,
    snapshot,
    verify_checkout,
)

FULL_DATASET = "f09cdec986858c5b1aa80b3c97aaa4d825be892fc94e16ac5d835bc3d709f0ce"
FULL_PREFIX = "f2bf006189ece6b1c96b8835ed1e1c7cbcab4675980d60da836f889f2958b89d"
FULL_PAIRS = "a68c2b878fb2fbf7fcc738096396fa952408053f283c0fcf6c2ec2bf4a22e774"
PARENT_DEADLINE = 1793150297.974828
DATASET_FILES = {
    "DATASET.json",
    "SOURCE_PAIRS.json",
    *{
        f"{split}-{kind}.npy"
        for split in ["train", "validation", "test"]
        for kind in ["features", "targets"]
    },
    *{f"{split}-identities.jsonl" for split in ["train", "validation", "test"]},
}


def artifact_limit(name):
    if name in {"dataset/SOURCE_PAIRS.json", "prefix/PAIR_HASHES.jsonl"}:
        return 128 * 1024**2
    if name.endswith(".npy") or name.endswith("-identities.jsonl"):
        return 8 * 1024**3
    if re.fullmatch(r"corpus/[0-9]{6}/[0-9]{9}\.json", name):
        return 64 * 1024**2
    return 4 * 1024**2


def sha(path, maximum=128 * 1024**2):
    require(
        Path(path).is_file()
        and not Path(path).is_symlink()
        and Path(path).stat().st_size <= maximum,
        "data catalog hash byte ceiling exceeded",
    )
    result = hashlib.sha256()
    count = 0
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1048576), b""):
            count += len(block)
            require(count <= maximum, "growing catalog hash exceeded byte ceiling")
            result.update(block)
    return result.hexdigest()


def small_document(path, maximum, expected=None):
    path = Path(path)
    require(
        path.is_file() and not path.is_symlink() and 0 < path.stat().st_size <= maximum,
        "data catalog metadata is missing, linked or excessive",
    )
    with Bundle(path.parent, 30) as view:
        raw = view.bytes(path.name, maximum)
    if expected is not None:
        require(
            hashlib.sha256(raw).hexdigest() == digest_text(expected),
            "data catalog metadata differs from frozen identity",
        )
    return strict_json(raw)


def contract(path, expected, expected_commit, diagnostic=False):
    digest_text(expected)
    value = small_document(path, 128 * 1024**2, expected)
    require(
        isinstance(value, dict)
        and set(value)
        == {
            "schema",
            "status",
            "profile",
            "source_commit",
            "dataset_sha256",
            "pairs",
            "output",
            "resources",
            "shards",
            "files",
        },
        "data catalog field inventory differs",
    )
    require(
        value["schema"] == "caissa-original-data-catalog-v1"
        and value["status"] == "frozen",
        "data catalog is unsupported or not frozen",
    )
    require(
        re.fullmatch("[0-9a-f]{40}", expected_commit or "")
        and value["source_commit"] == expected_commit,
        "data catalog verifier source differs from external identity",
    )
    require(
        value["profile"] == ("diagnostic" if diagnostic else "full"),
        "data catalog profile mismatch; diagnostic work cannot certify full data",
    )
    digest_text(value["dataset_sha256"])
    relative_path(value["output"])
    require(
        type(value["pairs"]) is int
        and 1 <= value["pairs"] <= (100 if diagnostic else 500000),
        "data catalog pair count outside bound",
    )
    limits = value["resources"]
    expected_limits = {
        "maximum_wall_seconds": 120 if diagnostic else 21600,
        "maximum_active_seconds": 120 if diagnostic else 21600,
        "maximum_staging_seconds": 30 if diagnostic else 3600,
        "maximum_input_gib": 1 if diagnostic else 20,
        "maximum_additional_gib": 1 if diagnostic else 20,
        "minimum_free_gib": 1 if diagnostic else 10,
        "maximum_attempts": 1,
        "parent_deadline_unix": None if diagnostic else PARENT_DEADLINE,
    }
    require(
        isinstance(limits, dict)
        and set(limits) == set(expected_limits)
        and all(
            type(limits[k]) is type(v) and limits[k] == v
            for k, v in expected_limits.items()
        ),
        "data catalog cumulative resource ceilings differ",
    )
    require(
        isinstance(value["shards"], dict) and 1 <= len(value["shards"]) <= 16,
        "data catalog input-view count outside bound",
    )
    require(
        isinstance(value["files"], dict) and 0 < len(value["files"]) <= 500000,
        "data catalog artifact inventory outside bound",
    )
    if not diagnostic:
        require(
            value["dataset_sha256"] == FULL_DATASET and value["pairs"] == 114791,
            "full catalog changed the original frozen dataset or prefix",
        )
    required = {"dataset/" + name for name in DATASET_FILES}
    required |= {
        "config/studies.json",
        "config/strength-openings.json",
        "corpus/CONFIG.json",
    }
    required |= (
        {"corpus/SUMMARY.json"}
        if diagnostic
        else {
            "corpus/INTERRUPTED.json",
            "corpus/SESSIONS.jsonl",
            "prefix/PROTOCOL.json",
            "prefix/PAIR_HASHES.jsonl",
        }
    )
    required |= {f"corpus/{n//256:06d}/{n:09d}.json" for n in range(value["pairs"])}
    require(
        set(value["files"]) == required,
        "data catalog required array/identity/pair inventory is missing or extra",
    )
    if not diagnostic:
        require(
            value["files"]["prefix/PROTOCOL.json"]["sha256"] == FULL_PREFIX
            and value["files"]["prefix/PAIR_HASHES.jsonl"]["sha256"] == FULL_PAIRS,
            "full data catalog changed original fixed-prefix authorization",
        )
    seen = set()
    for name, ref in value["files"].items():
        relative_path(name)
        require(
            isinstance(ref, dict)
            and set(ref) == {"shard", "path", "sha256"}
            and ref["shard"] in value["shards"],
            "data catalog artifact reference differs",
        )
        relative_path(ref["path"])
        digest_text(ref["sha256"])
        identity = (ref["shard"], ref["path"])
        require(
            identity not in seen, "data catalog reuses one input for distinct artifacts"
        )
        seen.add(identity)
    return value


def input_path(root, name):
    path = Path(root) / relative_path(name)
    require(
        path.resolve().is_relative_to(Path(root).resolve()) and not path.is_symlink(),
        "data catalog input path escaped its trusted root or is linked",
    )
    return path


@contextlib.contextmanager
def views(rule, input_root, maximum_seconds, guard):
    """Verify selected input subsets without mutating original directories."""
    started, wall = time.monotonic(), time.time()
    with contextlib.ExitStack() as stack:
        result, declared = {}, set()
        for key, descriptor in rule["shards"].items():
            require(
                isinstance(descriptor, dict)
                and set(descriptor) == {"root", "manifest", "manifest_sha256"},
                "data catalog input-view descriptor differs",
            )
            guard()
            remaining = min(
                maximum_seconds - (time.monotonic() - started),
                maximum_seconds - (time.time() - wall),
            )
            require(remaining > 0, "data catalog original staging deadline exhausted")
            manifest = input_path(input_root, descriptor["manifest"])
            document = small_document(
                manifest, 64 * 1024**2, descriptor["manifest_sha256"]
            )
            require(
                isinstance(document, dict)
                and set(document) == {"schema", "files"}
                and document["schema"] == "caissa-input-view-v1"
                and isinstance(document["files"], dict),
                "data catalog input-view schema differs",
            )
            selected = {
                r["path"]: r["sha256"]
                for r in rule["files"].values()
                if r["shard"] == key
            }
            byte_limits = {
                ref["path"]: artifact_limit(name)
                for name, ref in rule["files"].items()
                if ref["shard"] == key
            }
            require(
                selected and document["files"] == selected,
                "data catalog view omitted or added a declared artifact",
            )
            view = stack.enter_context(
                Bundle(input_path(input_root, descriptor["root"]), min(3600, remaining))
            )
            for name, expected in selected.items():
                guard()
                relative_path(name)
                require(
                    view.sha(name, byte_limits[name]) == digest_text(expected),
                    "data catalog original input bytes differ",
                )
                declared.add((key, name))
            view.identities = selected
            result[key] = view
        require(
            len(declared) == len(rule["files"]),
            "data catalog view inventory is incomplete",
        )
        yield result


def admit(rule, sources, diagnostic, tick=None):
    def document(name, maximum=4 * 1024**2):
        ref = rule["files"][name]
        return sources[ref["shard"]].json(ref["path"], maximum)

    manifest = document("dataset/DATASET.json")
    require(
        rule["files"]["dataset/DATASET.json"]["sha256"] == rule["dataset_sha256"],
        "data catalog dataset identity differs",
    )
    require(
        manifest.get("schema") == "caissa-dataset-v2"
        and manifest.get("functional_deduplication") is True,
        "data catalog lacks functional-input screening",
    )
    for name, expected in manifest["files"].items():
        require(
            rule["files"]["dataset/" + name]["sha256"] == expected,
            "data catalog prepared array differs from original dataset",
        )
    require(
        rule["files"]["dataset/SOURCE_PAIRS.json"]["sha256"]
        == manifest["source_pairs_sha256"],
        "data catalog original pair lineage differs",
    )
    for name in ["config/studies.json", "config/strength-openings.json"]:
        require(
            rule["files"][name]["sha256"] == manifest["heldout_inputs"][name],
            "data catalog held-out inputs changed",
        )
    corpus = document("corpus/CONFIG.json")
    require(
        corpus == manifest["corpus_config"],
        "data catalog original corpus configuration differs",
    )
    # Also inspect the original source namespace. Staging a subset must not hide
    # additional games written after the frozen acquisition stopped.
    ref = rule["files"]["corpus/CONFIG.json"]
    view = sources[ref["shard"]]
    require(
        ref["path"] == "CONFIG.json",
        "data catalog corpus view must retain its original root",
    )
    observed = set()
    for directory in view.root.iterdir():
        if tick is not None:
            tick()
        if re.fullmatch("[0-9]{6}", directory.name):
            require(
                directory.is_dir() and not directory.is_symlink(),
                "linked original corpus partition",
            )
            for pair in directory.iterdir():
                if tick is not None:
                    tick()
                if pair.suffix == ".json":
                    require(
                        re.fullmatch(r"[0-9]{9}\.json", pair.name)
                        and not pair.is_symlink(),
                        "unexpected original corpus journal path",
                    )
                    observed.add(directory.name + "/" + pair.name)
                    require(
                        len(observed) <= 500000,
                        "original corpus inventory exceeds bound",
                    )
    expected = {f"{n//256:06d}/{n:09d}.json" for n in range(rule["pairs"])}
    require(
        observed == expected, "original corpus has missing or additional paired games"
    )
    if not diagnostic:
        require(
            not (view.root / "SUMMARY.json").exists(),
            "original failed acquisition was replaced with success",
        )
        require(
            manifest["splits"]["train"] >= 10000000
            and manifest["counts"]["completed_games"] >= 100000,
            "full data catalog mandatory game/input floors failed",
        )
    return manifest


def execute(path, expected, input_root, output, expected_commit, diagnostic=False):
    from tools.heuristic_study import avoid_decisive_matches

    avoid_decisive_matches()
    avoid_decisive_matches(Path(__file__).resolve().parents[1] / "runs")
    rule = contract(path, expected, expected_commit, diagnostic)
    code = Path(__file__).resolve().parents[1]
    actual = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=code, text=True, timeout=5
    ).strip()
    require(actual == expected_commit, "data catalog independent reader source changed")
    source_inputs = {
        "schema": "caissa-source-inputs-v2",
        "policy": PRODUCT,
        "commit": actual,
        "files": snapshot(code, actual, PRODUCT),
    }
    verify_checkout(code, source_inputs, actual, PRODUCT)
    limits = rule["resources"]
    parent = limits["parent_deadline_unix"]
    require(
        parent is None or time.time() + limits["maximum_wall_seconds"] <= parent,
        "data replay cannot fit the original parent project deadline",
    )
    output = Path(output).resolve()
    input_root = Path(input_root).resolve()
    require(
        output == input_path(input_root, rule["output"]).resolve(),
        "changing the frozen output cannot create a new data replay budget",
    )
    require(
        not output.exists(), "data replay output already exists; scope cannot be reset"
    )
    source_roots = set()
    for descriptor in rule["shards"].values():
        require(
            isinstance(descriptor, dict)
            and set(descriptor) == {"root", "manifest", "manifest_sha256"},
            "data catalog input-view descriptor differs",
        )
        source_root = input_path(input_root, descriptor["root"]).resolve()
        require(
            source_root not in source_roots,
            "data catalog aliases an original input root",
        )
        source_roots.add(source_root)
        require(
            not output.is_relative_to(source_root),
            "data replay output would modify an original input directory",
        )
    power = PowerGuard(POLICY if not diagnostic and sys.platform == "darwin" else None)
    scope = RecoveryScope(
        output,
        {
            "catalog_sha256": expected,
            "source_commit": expected_commit,
            "dataset_sha256": rule["dataset_sha256"],
            "profile": rule["profile"],
        },
        limits["maximum_wall_seconds"],
        output / "empty-input-accounting",
        limits["minimum_free_gib"],
        limits["maximum_additional_gib"],
        maximum_active_seconds=limits["maximum_active_seconds"],
    )
    campaign = None
    try:
        power.start(output)
        stage_start, stage_wall = time.monotonic(), time.time()

        def guard():
            scope.check()
            power.check()
            require(
                time.monotonic() - stage_start < limits["maximum_staging_seconds"]
                and time.time() - stage_wall < limits["maximum_staging_seconds"],
                "data catalog original staging deadline exhausted",
            )

        from tools.finalize_corpus import archive_source

        atomic(output / "SOURCE_INPUTS.json", source_inputs)
        archive_source(code, output / "source", actual, source_inputs["files"])
        with Bundle(
            Path(path).resolve().parent, min(30, scope.remaining())
        ) as catalog_view:
            catalog_bytes = catalog_view.bytes(Path(path).name, 128 * 1024**2)
            require(
                hashlib.sha256(catalog_bytes).hexdigest() == expected,
                "data catalog changed before its owned snapshot",
            )
            (output / "CATALOG.json").write_bytes(catalog_bytes)
            del catalog_bytes
        guard()
        raw = output / "raw"
        raw.mkdir()
        total = 0
        with views(
            rule, input_root, limits["maximum_staging_seconds"], guard
        ) as sources:
            manifest = admit(rule, sources, diagnostic, tick=guard)
            declared_bytes = 0
            for ref in rule["files"].values():
                guard()
                stream, info = sources[ref["shard"]].open(ref["path"])
                stream.close()
                declared_bytes += info.st_size
            require(
                declared_bytes <= limits["maximum_input_gib"] * 1024**3,
                "data catalog combined input byte ceiling exhausted",
            )
            for name, ref in rule["files"].items():
                guard()
                destination = raw / name
                destination.parent.mkdir(parents=True, exist_ok=True)
                record = sources[ref["shard"]].copy(
                    ref["path"], destination, artifact_limit(name), check=guard
                )
                total += record["bytes"]
                require(
                    total <= limits["maximum_input_gib"] * 1024**3,
                    "data catalog combined input byte ceiling exhausted",
                )

        # The source views' one-hour leases end here. The separate six-hour
        # reconstruction remains charged to the same original cumulative scope.
        def replay_guard():
            scope.check()
            power.check()

        launcher = "import runpy,sys;sys.path.insert(0,sys.argv.pop(1));runpy.run_module('verification.dataset',run_name='__main__')"
        command = [
            sys.executable,
            "-P",
            "-c",
            launcher,
            str(output / "source"),
            "dataset",
            "corpus",
            "--studies",
            "config/studies.json",
            "--openings",
            "config/strength-openings.json",
            "--scratch",
            str(output / "index"),
            "--progress",
            str(output / "DATA_PROGRESS.json"),
            "--retain-index",
            "--max-seconds",
            str(scope.remaining()),
            "--max-wall-seconds",
            str(scope.remaining()),
            "--wall-deadline-unix",
            str(scope.deadline),
        ]
        if not diagnostic:
            command += [
                "--require-full",
                "--fixed-prefix-protocol",
                "prefix/PROTOCOL.json",
                "--expected-prefix-protocol-sha256",
                FULL_PREFIX,
                "--pair-manifest",
                "prefix/PAIR_HASHES.jsonl",
            ]
        campaign = Campaign(
            output / "execution",
            {
                "catalog_sha256": expected,
                "source_commit": actual,
                "component": "original-data",
                "full_acceptance": False,
            },
            scope.remaining(),
            absolute_deadline=scope.deadline,
            resource_guard=replay_guard,
        )
        try:
            record = campaign.run(
                "independent",
                command,
                scope.remaining(),
                cwd=raw,
                maximum_output_bytes=4 * 1024**2,
            )
        except StageFailure as error:
            raise ValueError(
                "independent original-data replay failed; inspect preserved execution"
            ) from error
        result = strict_json((output / "execution/independent.log").read_bytes())
        require(
            record["exit"] == 0
            and result.get("status") == "passed"
            and result.get("dataset_sha256") == rule["dataset_sha256"]
            and result.get("profile")
            == ("diagnostic-data-replay" if diagnostic else "full-data-replay"),
            "data catalog reader did not reconstruct the declared original data",
        )
        replay_guard()
        result.update(
            gate="G07",
            component="data",
            component_pass=not diagnostic,
            catalog_sha256=expected,
            verifier_source_commit=actual,
            full_gate=False,
            full_acceptance=False,
            learning_replay_join_required=True,
        )
        atomic(output / "DATA.json", result)
        campaign.close(
            "passed-data-component" if not diagnostic else "passed-diagnostic-data",
            result,
        )
        return result
    except BaseException as error:
        atomic(
            output / "FAILED.json",
            {
                "status": "failed",
                "reason": str(error),
                "full_gate": False,
                "full_acceptance": False,
            },
        )
        raise
    finally:
        if campaign is not None and not campaign.closed:
            campaign.close("failed")
        if power is not None:
            power.close()
        scope.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("catalog", type=Path)
    parser.add_argument("--expected-catalog-sha256", required=True)
    parser.add_argument("--expected-commit", required=True)
    parser.add_argument("--input-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--diagnostic", action="store_true")
    args = parser.parse_args()
    try:
        result = execute(
            args.catalog,
            args.expected_catalog_sha256,
            args.input_root,
            args.output,
            args.expected_commit,
            args.diagnostic,
        )
        print(json.dumps(result))
        return 0
    except (
        ValueError,
        KeyError,
        TypeError,
        OSError,
        subprocess.SubprocessError,
    ) as error:
        print(
            json.dumps(
                {"status": "rejected", "reason": str(error), "full_acceptance": False}
            )
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
