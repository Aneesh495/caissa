"""Independent binding of an authorized fixed prefix to its failed acquisition.

This interprets a prospectively frozen recovery protocol, never a producer's
pass flag. The original failure is required and cannot become a success here.
"""

import hashlib
import json
import math
from pathlib import Path

from verification.protocol import read_json


def sha(path):
    result = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(block)
    return result.hexdigest()


def require(condition, reason):
    if not condition:
        raise ValueError(reason)


def protocol(path, expected):
    require(
        expected is not None and sha(path) == expected,
        "fixed-prefix protocol differs from its external frozen identity",
    )
    rule = read_json(Path(path).read_text())
    require(
        rule["schema"] == "caissa-fixed-prefix-finalization-v1"
        and rule["status"] == "frozen",
        "fixed-prefix recovery protocol is inactive or unsupported",
    )
    require(
        type(rule["completed_pairs"]) is int and 1 <= rule["completed_pairs"] <= 500000,
        "invalid fixed-prefix pair count",
    )
    require(
        type(rule["maximum_wall_seconds"]) is int
        and 0 < rule["maximum_wall_seconds"] <= 21600
        and rule["maximum_new_games"] == 0,
        "recovery would extend its authorized resource or generation scope",
    )
    require(
        rule["minimum_training_inputs"] >= 10000000
        and rule["minimum_completed_games"] >= 100000
        and 0.95 <= rule["minimum_completed_search_fraction"] <= 1,
        "recovery weakens mandatory data endpoints",
    )
    require(
        rule["minimum_free_gib"] >= 10
        and 0 < rule["maximum_additional_disk_gib"] <= 20,
        "recovery disk ceiling or reserve differs",
    )
    require(
        rule["prior_failure"] == "preparation-confirmation-timeout",
        "unsupported prior acquisition failure",
    )
    for key in [
        "corpus_config_sha256",
        "pair_hash_manifest_sha256",
        "teacher_sha256",
        "prior_interrupted_sha256",
        "prior_sessions_sha256",
    ]:
        value = rule[key]
        require(
            type(value) is str
            and len(value) == 64
            and all(c in "0123456789abcdef" for c in value),
            "invalid frozen acquisition identity: " + key,
        )
    return rule


def prefix(rule, corpus, manifest_path, *, check=None, verify_bytes=False):
    """Read each preserved identity and reject additions or omitted pairs."""
    corpus, manifest_path = Path(corpus), Path(manifest_path)
    require(
        sha(corpus / "CONFIG.json") == rule["corpus_config_sha256"],
        "recovery corpus configuration changed",
    )
    require(
        sha(corpus / "INTERRUPTED.json") == rule["prior_interrupted_sha256"]
        and sha(corpus / "SESSIONS.jsonl") == rule["prior_sessions_sha256"],
        "original failed acquisition history changed",
    )
    config = read_json((corpus / "CONFIG.json").read_text())
    failure = read_json((corpus / "INTERRUPTED.json").read_text())
    require(
        config["engine_sha256"] == rule["teacher_sha256"]
        and config.get("search_policy") == "searched-v2"
        and config["nodes"] == 2000,
        "fixed-prefix teacher or searched policy differs",
    )
    require(
        failure["status"] == "interrupted"
        and failure["stop_reason"] == rule["prior_failure"]
        and failure["pairs"] == rule["completed_pairs"],
        "original failed acquisition receipt differs",
    )
    require(
        not (corpus / "SUMMARY.json").exists(),
        "recovery original failure was replaced with a completion receipt",
    )
    require(
        sha(manifest_path) == rule["pair_hash_manifest_sha256"],
        "preserved prefix identity manifest changed",
    )
    require(
        manifest_path.stat().st_size <= 128 * 1024 * 1024,
        "preserved prefix manifest byte ceiling",
    )
    rows = []
    with manifest_path.open() as stream:
        for number, line in enumerate(stream):
            if check is not None and number % 256 == 0:
                check()
            row = read_json(line)
            name = f"{number//256:06d}/{number:09d}.json"
            require(
                set(row) == {"path", "sha256"} and row["path"] == name,
                "fixed-prefix identities are missing, reordered or unsafe",
            )
            value = row["sha256"]
            require(
                type(value) is str
                and len(value) == 64
                and all(c in "0123456789abcdef" for c in value),
                "invalid preserved pair checksum",
            )
            if verify_bytes:
                require(
                    not (corpus / name).is_symlink() and sha(corpus / name) == value,
                    "preserved original pair bytes changed",
                )
            rows.append({"pair": number, "sha256": value})
    require(
        len(rows) == rule["completed_pairs"], "fixed-prefix inventory length differs"
    )
    actual = {str(path.relative_to(corpus)) for path in corpus.glob("*/*.json")}
    require(
        actual == {f'{r["pair"]//256:06d}/{r["pair"]:09d}.json' for r in rows},
        "recovery corpus gained or lost original pair journals",
    )
    return rows


def endpoints(rule, splits, completed_games, raw, searched):
    require(
        splits["train"] >= rule["minimum_training_inputs"]
        and completed_games >= rule["minimum_completed_games"],
        "full original game/training-input floors not met",
    )
    require(
        splits["validation"] > 0 and splits["test"] > 0,
        "required held-out split is empty",
    )
    require(
        raw > 0
        and 0 <= searched <= raw
        and searched / raw >= rule["minimum_completed_search_fraction"],
        "original teacher searched-depth fraction failed its frozen endpoint",
    )
    return {
        "completed_search_samples": searched,
        "all_original_samples": raw,
        "completed_search_fraction": searched / raw,
    }
