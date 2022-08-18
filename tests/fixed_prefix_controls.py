"""A small real corpus exercises recovery bindings without relaxing full floors."""

import argparse
import copy
import hashlib
import json
import shutil
from pathlib import Path

from verification.acquisition import protocol, prefix, endpoints, sha
from verification.dataset import verify_dataset


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--corpus", type=Path, required=True)
    ap.add_argument("--dataset", type=Path, required=True)
    ap.add_argument("--output", type=Path, required=True)
    args = ap.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    corpus = args.output / "corpus"
    shutil.copytree(args.corpus, corpus)
    (corpus / "SUMMARY.json").unlink()
    rows = [
        {"path": str(p.relative_to(corpus)), "sha256": sha(p)}
        for p in sorted(corpus.glob("*/*.json"))
    ]
    assert 0 < len(rows) < 50000
    failure = {
        "status": "interrupted",
        "stop_reason": "preparation-confirmation-timeout",
        "pairs": len(rows),
        "scope": "synthetic failed-owner fixture over unchanged real original games",
    }
    (corpus / "INTERRUPTED.json").write_text(json.dumps(failure) + "\n")
    preserved = args.output / "PAIR_HASHES.jsonl"
    preserved.write_text(
        "".join(json.dumps(r, separators=(",", ":")) + "\n" for r in rows)
    )
    config = json.loads((corpus / "CONFIG.json").read_text())
    rule = {
        "schema": "caissa-fixed-prefix-finalization-v1",
        "status": "frozen",
        "maximum_wall_seconds": 21600,
        "maximum_new_games": 0,
        "completed_pairs": len(rows),
        "minimum_training_inputs": 10000000,
        "minimum_completed_games": 100000,
        "minimum_completed_search_fraction": 0.95,
        "minimum_free_gib": 10,
        "maximum_additional_disk_gib": 20,
        "heldout_inputs": {
            f: sha(f) for f in ["config/studies.json", "config/strength-openings.json"]
        },
        "prior_failure": "preparation-confirmation-timeout",
        "corpus_config_sha256": sha(corpus / "CONFIG.json"),
        "pair_hash_manifest_sha256": sha(preserved),
        "teacher_sha256": config["engine_sha256"],
        "prior_interrupted_sha256": sha(corpus / "INTERRUPTED.json"),
        "prior_sessions_sha256": sha(corpus / "SESSIONS.jsonl"),
    }
    rulepath = args.output / "PROTOCOL.json"
    rulepath.write_text(json.dumps(rule) + "\n")
    expected = sha(rulepath)
    checked = protocol(rulepath, expected)
    inventory = prefix(checked, corpus, preserved, verify_bytes=True)
    assert len(inventory) == len(rows)
    results = []

    def reject(name, fn, text):
        try:
            fn()
        except ValueError as error:
            assert text in str(error), (name, str(error))
            results.append({"case": name, "reason": str(error)})
        else:
            raise AssertionError("invalid recovery accepted: " + name)

    changed = copy.deepcopy(rule)
    changed["minimum_training_inputs"] = 9999999
    rulepath.write_text(json.dumps(changed) + "\n")
    reject(
        "rehashed-weakened-floor",
        lambda: protocol(rulepath, sha(rulepath)),
        "weakens mandatory",
    )
    reject(
        "external-protocol-identity",
        lambda: protocol(rulepath, expected),
        "external frozen identity",
    )
    rulepath.write_text(json.dumps(rule) + "\n")
    extra = corpus / "999999/999999999.json"
    extra.parent.mkdir()
    extra.write_text("{}\n")
    reject(
        "extra-original-pair",
        lambda: prefix(checked, corpus, preserved),
        "gained or lost",
    )
    extra.unlink()
    extra.parent.rmdir()
    (corpus / "SUMMARY.json").write_text('{"status":"completed"}\n')
    reject(
        "erased-original-failure",
        lambda: prefix(checked, corpus, preserved),
        "replaced with a completion",
    )
    (corpus / "SUMMARY.json").unlink()
    original = (corpus / "SESSIONS.jsonl").read_bytes()
    (corpus / "SESSIONS.jsonl").write_bytes(original + b"{}\n")
    reject(
        "new-acquisition-session",
        lambda: prefix(checked, corpus, preserved),
        "history changed",
    )
    (corpus / "SESSIONS.jsonl").write_bytes(original)
    reject(
        "searched-quality-floor",
        lambda: endpoints(
            checked, {"train": 10000000, "validation": 1, "test": 1}, 100000, 100, 94
        ),
        "searched-depth fraction",
    )
    reject(
        "actual-small-corpus-full-refusal",
        lambda: verify_dataset(
            args.dataset,
            corpus,
            Path("config/studies.json"),
            Path("config/strength-openings.json"),
            True,
            fixed_prefix_protocol=rulepath,
            expected_protocol_sha256=expected,
            pair_manifest=preserved,
            maximum_seconds=60,
        ),
        "floors not met",
    )
    report = {
        "status": "passed",
        "real_original_pairs": len(rows),
        "controls": results,
        "synthetic_metadata": "Only the failed-owner fixture is synthetic; original games and prepared arrays are unchanged",
        "full_acceptance": False,
    }
    (args.output / "CONTROLS.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report))


if __name__ == "__main__":
    main()
