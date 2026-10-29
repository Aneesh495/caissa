"""Full raw-state reconstruction and fresh saved-native restoration replay."""

import argparse
import hashlib
import json
import math
import os
import shutil
import time
from pathlib import Path

from tools.campaign_process import atomic
from tools.restoration_journal import open_journal
from verification.bundle import strict_json
from verification.network_bytes import QuantizedNetwork
from verification.restoration_state import Shadow, require, same_type, state_commands
from verification.tactical_generation import Probe

PROFILE_SHA256 = "6cde330d87e49084135760cb737f3c2756a594a69b4ed709e21b98df5f9e584c"


def digest(path):
    value = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1048576), b""):
            value.update(block)
    return value.hexdigest()


def document(path):
    path = Path(path)
    require(
        path.is_file()
        and not path.is_symlink()
        and 0 < path.stat().st_size <= 4 * 1024 * 1024,
        "restoration metadata missing, linked or excessive",
    )
    return strict_json(path.read_bytes())


def verify(
    observations,
    summary_path,
    config_path,
    engine,
    expected_engine,
    network,
    expected_network,
    profile_path,
    expected_profile,
    expected_observations,
    output,
    *,
    mode="full",
    maximum_seconds=3600,
    compressed_journals=False,
):
    from tools.heuristic_study import avoid_decisive_matches

    avoid_decisive_matches()
    require(mode in {"full", "diagnostic"}, "unknown restoration verification mode")
    require(
        expected_profile == PROFILE_SHA256 and digest(profile_path) == PROFILE_SHA256,
        "restoration prospective profile differs",
    )
    rule, config, summary = (
        document(profile_path),
        document(config_path),
        document(summary_path),
    )
    require(
        math.isfinite(maximum_seconds)
        and 0 < maximum_seconds <= rule["maximum_independent_seconds"],
        "restoration independent duration exceeds original bound",
    )
    pairs = config.get("pairs")
    require(
        type(pairs) is int and 1 <= pairs <= rule["transitions"],
        "restoration sample count invalid",
    )
    require(
        mode != "full" or pairs == rule["transitions"],
        "full restoration requires all1000000 make/unmake pairs",
    )
    require(
        config["schema"] == "caissa-restoration-sample-v1"
        and summary["schema"] == "caissa-restoration-summary-v1",
        "restoration metadata schema differs",
    )
    for field, expected in [
        ("engine_sha256", expected_engine),
        ("network_sha256", expected_network),
        ("profile_sha256", expected_profile),
    ]:
        require(
            config[field] == summary[field] == expected,
            "restoration metadata actor/profile identity differs",
        )
    require(
        expected_network == rule["network_sha256"]
        and digest(network) == expected_network
        and digest(engine) == expected_engine,
        "restoration externally pinned actor bytes differ",
    )
    require(
        summary["observations_sha256"] == expected_observations
        and summary["native_exit"] == 0
        and summary["status"] == "observed",
        "restoration raw identity or actual native exit differs",
    )
    require(
        type(config["maximum_seconds"]) in {int, float}
        and math.isfinite(config["maximum_seconds"])
        and 0 < config["maximum_seconds"] <= rule["maximum_producer_seconds"]
        and config["maximum_observation_bytes"] == rule["maximum_observation_bytes"],
        "restoration producer bounds changed",
    )
    observations, output = Path(observations), Path(output)
    require(
        type(compressed_journals) is bool
        and config.get("journal_encoding", "plain-jsonl-v1")
        == ("gzip-v1" if compressed_journals else "plain-jsonl-v1"),
        "restoration journal transport differs from producer declaration",
    )
    require(
        observations.is_file()
        and not observations.is_symlink()
        and 0 < observations.stat().st_size <= rule["maximum_observation_bytes"],
        "restoration raw file missing, linked or excessive",
    )
    output.mkdir(parents=True, exist_ok=False)
    started, active = time.time(), time.monotonic()
    deadline = started + maximum_seconds
    atomic(
        output / "CONFIG.json",
        {
            "mode": mode,
            "pairs": pairs,
            "engine_sha256": expected_engine,
            "network_sha256": expected_network,
            "profile_sha256": expected_profile,
            "observations_sha256": expected_observations,
            "maximum_seconds": maximum_seconds,
            "deadline_unix": deadline,
            "full_acceptance": False,
        },
    )
    saved_engine, saved_network = output / "caissa", output / "selected.cai"
    shutil.copyfile(engine, saved_engine)
    saved_engine.chmod(0o755)
    shutil.copyfile(network, saved_network)
    require(
        digest(saved_engine) == expected_engine
        and digest(saved_network) == expected_network,
        "copied restoration actor changed",
    )
    model = QuantizedNetwork(saved_network)
    require(
        model.identity == rule["checkpoint_sha256"]
        and model.width == 64
        and model.version == 4,
        "restoration selected float lineage or integer encoding differs",
    )
    oracle = Shadow(model)
    native = None
    closed = False
    requests = completed = resets = nulls = records = 0
    raw_hash = hashlib.sha256()
    last = None
    before = None
    try:
        native = Probe(
            saved_engine, ["--state-probe", str(saved_network.resolve())], deadline
        )
        with (
            open_journal(observations, "rb", compressed=compressed_journals, maximum_bytes=rule["maximum_observation_bytes"]) as stream,
            open_journal(output / ("native-replay.jsonl.gz" if compressed_journals else "native-replay.jsonl"), "xb", compressed=compressed_journals, maximum_bytes=rule["maximum_replay_bytes"]) as replay,
        ):
            original_stat = os.fstat(stream.fileno())

            def tick():
                require(
                    time.time() < deadline
                    and time.monotonic() - active < maximum_seconds,
                    "restoration independent cumulative deadline exhausted",
                )

            def ask(command, recorded, expected_reply):
                nonlocal requests, last
                tick()
                last = {"command": command, "recorded": recorded}
                actual = native.request(command)
                requests += 1
                reply = hashlib.sha256(native.last_response).hexdigest()
                last["actual"] = actual
                require(
                    actual == recorded and reply == expected_reply,
                    "fresh native restoration response differs from saved raw state",
                )
                for field, value in actual.items():
                    require(
                        same_type(recorded[field], value),
                        "restoration state wire type differs: " + field,
                    )
                entry = (
                    json.dumps(
                        {
                            "request": requests,
                            "command": command,
                            "reply_sha256": reply,
                        },
                        separators=(",", ":"),
                    )
                    + "\n"
                ).encode()
                replay.write(entry)
                require(
                    replay.tell() <= rule["maximum_replay_bytes"],
                    "restoration fresh replay byte ceiling exhausted",
                )
                return actual

            for expected in state_commands(rule, pairs):
                tick()
                raw = stream.readline(128 * 1024 + 1)
                require(
                    raw and raw.endswith(b"\n") and len(raw) <= 128 * 1024,
                    "missing or excessive restoration observation record",
                )
                raw_hash.update(raw)
                record = strict_json(raw)
                records += 1
                require(
                    record.get("kind") == expected["kind"]
                    and type(record.get("index")) is int
                    and record["index"] == expected["index"],
                    "restoration reachable sequence index differs",
                )
                if expected["kind"] == "reset":
                    require(
                        set(record)
                        == {"kind", "index", "fen", "chess960", "state", "reply_sha256"}
                        and record["fen"] == expected["fen"]
                        and type(record["chess960"]) is bool
                        and record["chess960"] == expected["chess960"],
                        "restoration reset does not follow frozen reachable walk",
                    )
                    oracle.reset(expected["fen"], expected["chess960"])
                    command = (
                        "reset "
                        + ("960|" if expected["chess960"] else "")
                        + expected["fen"]
                    )
                    before = ask(command, record["state"], record["reply_sha256"])
                    oracle.check(before)
                    resets += 1
                elif expected["kind"] == "null":
                    require(
                        set(record) == {"kind", "index", "states"}
                        and len(record["states"]) == 4,
                        "restoration null observation inventory differs",
                    )
                    for saved, command in zip(
                        record["states"], ["null", "null", "undo", "undo"], strict=True
                    ):
                        require(
                            set(saved) == {"command", "state", "reply_sha256"}
                            and saved["command"] == command,
                            "restoration null operation differs",
                        )
                        if command == "null":
                            oracle.push("null")
                        else:
                            oracle.pop()
                        actual = ask(command, saved["state"], saved["reply_sha256"])
                        oracle.check(actual)
                    require(
                        actual == before,
                        "null restoration changed the complete parent state",
                    )
                    nulls += 1
                else:
                    require(
                        set(record)
                        == {
                            "kind",
                            "index",
                            "move",
                            "after",
                            "restored",
                            "after_reply_sha256",
                            "restored_reply_sha256",
                            "commit_reply_sha256",
                        }
                        and record["move"] == expected["move"],
                        "restoration move differs from frozen reachable walk",
                    )
                    oracle.push(record["move"])
                    after = ask(
                        "move " + record["move"],
                        record["after"],
                        record["after_reply_sha256"],
                    )
                    oracle.check(after)
                    oracle.pop()
                    restored = ask(
                        "undo", record["restored"], record["restored_reply_sha256"]
                    )
                    require(
                        restored == before,
                        "restoration failed exact parent board/history/neural equality",
                    )
                    oracle.push(record["move"])
                    before = ask(
                        "move " + record["move"],
                        record["after"],
                        record["commit_reply_sha256"],
                    )
                    completed += 1
                if completed % 1024 == 0 or completed == pairs:
                    replay.flush()
                    atomic(
                        output / "PROGRESS.json",
                        {
                            "pairs": completed,
                            "requests": requests,
                            "records": records,
                            "resets": resets,
                            "null_branches": nulls,
                            "elapsed_seconds": time.monotonic() - active,
                            "unix": time.time(),
                        },
                    )
            require(
                not stream.read(1),
                "restoration observation has unrequested trailing records",
            )
            final_stat = os.fstat(stream.fileno())
            require(
                (
                    original_stat.st_size,
                    original_stat.st_mtime_ns,
                    original_stat.st_ctime_ns,
                )
                == (final_stat.st_size, final_stat.st_mtime_ns, final_stat.st_ctime_ns),
                "restoration raw bytes changed during replay",
            )
            replay.flush()
        require(
            raw_hash.hexdigest() == expected_observations,
            "restoration complete raw observation digest differs",
        )
        for key, value in [
            ("pairs", completed),
            ("requests", requests),
            ("resets", resets),
            ("null_branches", nulls),
        ]:
            require(
                type(summary[key]) is int and summary[key] == value,
                "restoration recomputed summary count differs: " + key,
            )
        native.close()
        closed = True
        require(
            native.process.returncode == 0 and not native.stderr,
            "fresh native restoration exit/stderr failure",
        )
        report = {
            "status": "passed",
            "pairs": completed,
            "requests": requests,
            "records": records,
            "resets": resets,
            "null_branches": nulls,
            "independent_full_state_checks": completed + resets + nulls * 4,
            "engine_sha256": expected_engine,
            "network_sha256": expected_network,
            "profile_sha256": expected_profile,
            "observations_sha256": raw_hash.hexdigest(),
            "full_gate": mode == "full" and completed == 1000000,
            "native_exit": native.process.returncode,
            "elapsed_seconds": time.monotonic() - active,
            "scope": "Every make/unmake pair reconstructed through independent board/history, integer features/evaluation and fresh native replies",
            "full_acceptance": False,
        }
        atomic(output / "RESTORATION.json", report)
        return report
    except BaseException as error:
        atomic(
            output / "FAILED.json",
            {
                "error": repr(error),
                "pairs": completed,
                "requests": requests,
                "last_observation": last,
                "unix": time.time(),
                "full_acceptance": False,
            },
        )
        raise
    finally:
        if native is not None:
            if not closed:
                native.close()
            (output / "native-stderr.log").write_bytes(native.stderr)


def main():
    parser = argparse.ArgumentParser()
    for name in [
        "observations",
        "summary",
        "config",
        "engine",
        "network",
        "profile",
        "output",
    ]:
        parser.add_argument("--" + name, type=Path, required=True)
    for name in ["engine", "network", "profile", "observations"]:
        parser.add_argument("--expected-" + name + "-sha256", required=True)
    parser.add_argument("--mode", choices=["full", "diagnostic"], default="full")
    parser.add_argument("--maximum-seconds", type=float, default=3600)
    parser.add_argument("--gzip-journals", action="store_true")
    args = parser.parse_args()
    try:
        result = verify(
            args.observations,
            args.summary,
            args.config,
            args.engine,
            args.expected_engine_sha256,
            args.network,
            args.expected_network_sha256,
            args.profile,
            args.expected_profile_sha256,
            args.expected_observations_sha256,
            args.output,
            mode=args.mode,
            maximum_seconds=args.maximum_seconds,
            compressed_journals=args.gzip_journals,
        )
        print(json.dumps(result, allow_nan=False))
    except (ValueError, KeyError, TypeError, OSError, TimeoutError) as error:
        print(json.dumps({"status": "rejected", "reason": str(error)}))
        raise SystemExit(1)


if __name__ == "__main__":
    main()
