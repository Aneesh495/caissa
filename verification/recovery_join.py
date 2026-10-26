"""Join immutable historical recovery evidence to unchanged current producers.

No acquisition, interrupted trainer, data preparer or fault-injection producer
is run. Original receipt/source/program labels remain original. The saved final
image gets one separate protected-game resumption probe after raw reconstruction.
"""

import argparse
import hashlib
import json
import os
import shutil
import stat
import subprocess
import sys
import time
import zipfile
from pathlib import Path

from verification.bundle import Bundle, digest_text, strict_json
from verification.source import (
    NATIVE,
    PRODUCT,
    inventory,
    relative_path,
    require,
    snapshot,
    verify_checkout,
)

PROFILE = "b2c23e734029d13800a27e4f237b2855fdbdf718c11cecec30cbc42154a3f627"


def sha(path):
    from verification.runtime_binding import bounded

    return bounded(path, 4 * 1024**2)[1]


def extract(archive, prefix, destination, rule, tick):
    destination.mkdir(parents=True, exist_ok=False)
    selected = []
    with zipfile.ZipFile(archive) as reader:
        members = reader.infolist()
        require(
            0 < len(members) <= rule["maximum_archive_members"],
            "G11 historical archive member ceiling exceeded",
        )
        names = set()
        for member in members:
            tick()
            name = member.filename.rstrip("/")
            relative_path(name)
            require(name not in names, "G11 historical archive has duplicate paths")
            names.add(name)
            if member.is_dir() or not member.filename.startswith(prefix):
                continue
            name = relative_path(member.filename[len(prefix) :])
            mode = member.external_attr >> 16
            require(
                not stat.S_ISLNK(mode)
                and (stat.S_IFMT(mode) in {0, stat.S_IFREG})
                and member.file_size <= 128 * 1024**2
                and not member.flag_bits & 1,
                "G11 selected historical archive contains a link, excessive or encrypted file",
            )
            selected.append((member, name))
        require(
            0 < len(selected) <= 10000
            and sum(m.file_size for m, _ in selected) <= rule["maximum_selected_bytes"],
            "G11 positive historical component missing or excessive",
        )
        for member, name in selected:
            target = destination / name
            target.parent.mkdir(parents=True, exist_ok=True)
            length = 0
            with reader.open(member) as stream, target.open("xb") as output:
                while block := stream.read(1048576):
                    tick()
                    length += len(block)
                    require(
                        length <= member.file_size,
                        "G11 archive decompression exceeded declared length",
                    )
                    output.write(block)
            require(length == member.file_size, "G11 historical archive is truncated")
    require(
        (destination / "CONFIG.json").is_file(),
        "G11 original positive CONFIG was not selected",
    )
    return {
        "selected_files": len(selected),
        "selected_bytes": sum(m.file_size for m, _ in selected),
        "prefix": prefix,
    }


def source_boundaries(checkout, source, rule, origins):
    current = snapshot(checkout, source, PRODUCT)
    modes = {b.name: b.mode for b in inventory(checkout, source, PRODUCT)}
    native = snapshot(checkout, source, NATIVE)
    result = {}
    for role, names in rule["producer_footprints"].items():
        original_source = origins[role]["source_commit"]
        original = snapshot(checkout, original_source, PRODUCT)
        original_modes = {
            b.name: b.mode for b in inventory(checkout, original_source, PRODUCT)
        }
        require(
            all(
                name in current
                and current[name] == original.get(name)
                and modes[name] == original_modes.get(name)
                for name in names
            ),
            "G11 current producer footprint differs from original forced-recovery evidence: "
            + role,
        )
        require(
            native == snapshot(checkout, original_source, NATIVE),
            "G11 original component native source differs from current saved-image inputs: "
            + role,
        )
        result[role] = {
            "historical_source_commit": original_source,
            "current_source_commit": source,
            "unchanged_producer_files": {name: current[name] for name in names},
            "unchanged_producer_modes": {name: modes[name] for name in names},
            "native_inputs_unchanged": True,
        }
    return result


def verify(root, checkout, source, expected_inputs, output):
    from tools.host_lease import ENVIRONMENT, HostLease, inherited
    from tools.heuristic_study import avoid_decisive_matches

    checkout = Path(checkout).resolve()
    avoid_decisive_matches(checkout / "runs")
    previous = os.environ.get(ENVIRONMENT)
    lease = None
    if not inherited(checkout / "runs/TIMED_STRENGTH.lock"):
        lease = HostLease(checkout / "runs")
        os.environ[ENVIRONMENT] = str(lease.stream.fileno())
    try:
        return reconstruct(root, checkout, source, expected_inputs, output)
    finally:
        if lease is not None:
            if previous is None:
                os.environ.pop(ENVIRONMENT, None)
            else:
                os.environ[ENVIRONMENT] = previous
            lease.close()


def reconstruct(root, checkout, source, expected_inputs, output):
    from verification.arena_recovery import native_resume, verify as arena_replay
    from verification.data_recovery import verify as data_replay
    from verification.training_recovery import verify as training_replay

    root, output = Path(root).resolve(), Path(output).resolve()
    require(
        not output.is_relative_to(root) and not root.is_relative_to(output),
        "G11 full join must preserve original inputs",
    )
    output.mkdir(parents=True, exist_ok=False)
    start = time.monotonic()
    with Bundle(root, 300) as bundle:
        require(
            sha(root / "MANIFEST.json") == digest_text(expected_inputs),
            "G11 full join input manifest differs from external pin",
        )
        bundle.verify_manifest()
        require(
            bundle.identities["PROFILE.json"] == PROFILE,
            "G11 full join prospective profile differs",
        )
        rule = bundle.json("PROFILE.json")
        require(
            bundle.identities["ARTIFACTS.json"] == rule["artifacts_sha256"],
            "G11 historical artifact catalog differs",
        )
        origins, config = bundle.json("ARTIFACTS.json"), bundle.json("CONFIG.json")
        platform = "macos" if sys.platform == "darwin" else "linux"
        require(
            config.get("schema") == "caissa-recovery-join-inputs-v1"
            and config.get("source_commit") == source
            and config.get("platform") == platform
            and set(config.get("archives", {})) == {"arena", "training", "data"},
            "G11 full join source, platform or required component inventory differs",
        )
        require(
            config.get("profile_sha256") == PROFILE
            and config.get("engine_sha256")
            == bundle.identities["engine"]
            == rule["saved_engine_sha256"]
            and config.get("network_sha256")
            == bundle.identities["network.cai"]
            == rule["network_sha256"],
            "G11 full join changed the saved final actor",
        )
        verify_checkout(checkout, bundle.json("SOURCE_INPUTS.json"), source, PRODUCT)
        boundaries = source_boundaries(checkout, source, rule, origins)

        def tick():
            bundle.tick()
            require(
                shutil.disk_usage(output).free >= rule["minimum_free_bytes"]
                and sum(p.stat().st_size for p in output.rglob("*") if p.is_file())
                <= rule["maximum_output_bytes"],
                "G11 join output or reserve ceiling exhausted",
            )

        original = {}
        extraction = {}
        results = {}
        for role in ["arena", "training", "data"]:
            tick()
            descriptor = origins[role]["platforms"][platform]
            archive = bundle.reference(config["archives"][role])
            require(
                bundle.identities[archive] == descriptor["archive_sha256"]
                and (root / archive).stat().st_size
                == descriptor["archive_bytes"]
                <= rule["maximum_archive_bytes"],
                "G11 original ZIP identity or role differs: " + role,
            )
            raw = output / (role + "-original")
            extraction[role] = extract(
                root / archive, origins[role]["prefix"], raw, rule, tick
            )
            actual = strict_json((raw / "CONFIG.json").read_bytes())
            require(
                actual["source_commit"] == origins[role]["source_commit"],
                "G11 preserved historical source label differs: " + role,
            )
            seconds = min(
                60,
                bundle.monotonic_deadline - time.monotonic(),
                bundle.wall_deadline - time.time(),
            )
            require(
                seconds > 1,
                "G11 cumulative join deadline exhausted before reader start",
            )
            if role == "arena":
                result = arena_replay(
                    raw,
                    actual["engine_sha256"],
                    actual["source_commit"],
                    maximum_seconds=seconds,
                    tick=tick,
                )
                require(
                    result["raw_reconstruction_passed"] is True
                    and result["reconstructed_games"] == 4,
                    "G11 original arena reconstruction is incomplete",
                )
            elif role == "training":
                result = training_replay(
                    raw,
                    actual["engine_sha256"],
                    actual["source_commit"],
                    maximum_seconds=seconds,
                )
                require(
                    result["component_pass"] is True,
                    "G11 original tensor/optimizer reconstruction is incomplete",
                )
            else:
                result = data_replay(
                    raw, actual["source_commit"], maximum_seconds=seconds
                )
                require(
                    result["component_pass"] is True,
                    "G11 original SQL/split reconstruction is incomplete",
                )
            original[role], results[role] = raw, result
            write(output / (role + "-RECONSTRUCTION.json"), result)
        native_binding = native = None
        if platform == "macos":
            from verification.runtime_binding import inspect

            require(
                Path.cwd().resolve() == checkout,
                "G11 final-image replay requires the trusted source working directory",
            )
            native_binding = inspect(
                checkout,
                source,
                root / "V4.json",
                bundle.identities["V4.json"],
                root / "engine",
                root / "network.cai",
                root / "MODEL_CAMPAIGN.json",
            )
            native_started, native_wall = time.monotonic(), time.time()
            native = native_resume(
                original["arena"],
                output / "saved-native-resumption",
                strict_json((original["arena"] / "arena/CONFIG.json").read_bytes()),
                rule["saved_engine_sha256"],
                tick,
                lambda: min(
                    60 - (time.monotonic() - native_started),
                    native_wall + 60 - time.time(),
                    bundle.monotonic_deadline - time.monotonic(),
                    bundle.wall_deadline - time.time(),
                ),
                replay_engine=root / "engine",
            )
            require(
                native["engine_sha256"] == rule["saved_engine_sha256"]
                and native["new_games_executed"] == 3
                and native["game_journals"] == 4,
                "G11 saved final image failed its protected partial-pair resumption",
            )
        tick()
        require(
            sha(root / "MANIFEST.json") == expected_inputs,
            "G11 original join inputs changed during replay",
        )
        result = {
            "status": "passed",
            "gate": "G11",
            "source_commit": source,
            "input_manifest_sha256": expected_inputs,
            "platform": platform,
            "historical_producer_boundaries": boundaries,
            "original_archive_selection": extraction,
            "original_component_reconstructions": results,
            "saved_native_source_binding": native_binding,
            "saved_native_resumption": native,
            "new_acquisition": False,
            "new_training": False,
            "new_strength_games": 0,
            "full_gate": native is not None,
            "full_G11_saved_image_sample": native is not None,
            "full_acceptance": False,
            "elapsed_seconds": time.monotonic() - start,
            "scope": "Historical arena/training/data recovery plus unchanged current producer and exact saved-native join only. Other gates, compiler attribution and release remain independent.",
        }
        write(output / "G11.json", result)
        return result


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("root", type=Path)
    parser.add_argument("--checkout", type=Path, required=True)
    parser.add_argument("--expected-commit", required=True)
    parser.add_argument("--expected-inputs-sha256", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        print(
            json.dumps(
                verify(
                    args.root,
                    args.checkout,
                    args.expected_commit,
                    args.expected_inputs_sha256,
                    args.output,
                )
            )
        )
    except (
        ValueError,
        OSError,
        KeyError,
        TypeError,
        IndexError,
        zipfile.BadZipFile,
        subprocess.SubprocessError,
    ) as error:
        print(
            json.dumps(
                {
                    "status": "rejected",
                    "reason": str(error),
                    "full_gate": False,
                    "full_acceptance": False,
                }
            )
        )
        raise SystemExit(1)


if __name__ == "__main__":
    main()
