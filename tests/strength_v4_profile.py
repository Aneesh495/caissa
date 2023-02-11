"""Real immutable learning/actor lineage and rehashed prospective controls."""

import argparse
import copy
import fcntl
import json
import shutil
import subprocess
import zipfile
from pathlib import Path

from tools.campaign_process import atomic
from tools.heuristic_study import avoid_decisive_matches
from tools.strength_v4_profile import configuration, frozen_profile, lineage, sha
from verification.external_strength import external_options
from verification.strength import full_actor_options


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--published-inputs", action="store_true")
    args = parser.parse_args()
    avoid_decisive_matches()
    root = Path.cwd()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    proposed = json.loads((root / "config/protocol-v4.proposed.json").read_text())
    rule = copy.deepcopy(proposed)
    rule["status"] = "frozen"
    path = output / "PROFILE.json"
    atomic(path, rule)
    positive = frozen_profile(path, sha(path), root)
    model = root / "runs/searched-full-model-v3"
    engine = root / "build-search-semantics/caissa"
    network = root / "results/precision-v4-2026-10-25/selected-v4.cai"
    commit = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], text=True, timeout=5
    ).strip()
    if args.published_inputs or not model.exists() or not engine.exists():
        # Hosted hosts inspect the actual saved Mac actor bytes without
        # executing that foreign binary. No learning/model receipt is mocked.
        model = output / "published-learning"
        (model / "selection").mkdir(parents=True)
        for name in ["MODEL_CAMPAIGN.json", "INDEPENDENT_LEARNING.json"]:
            shutil.copy2(root / "results/full-model-v3-2026-10-25" / name, model / name)
        shutil.copy2(
            root / "results/full-model-v3-2026-10-25/SELECTION.json",
            model / "selection/SELECTION.json",
        )
        shutil.copy2(
            root / "results/precision-v4-inputs/selected.pt",
            model / "selection/selected.pt",
        )
        engine = output / "saved-macos-caissa"
        with zipfile.ZipFile(
            root / "results/search-semantics-2026-10-25/RAW.zip"
        ) as archive:
            engine.write_bytes(archive.read("semantic-attempt-001/independent/caissa"))
    derivation = lineage(root, model, engine, network, positive, commit)
    atomic(output / "REAL_LINEAGE.json", derivation)
    neural = configuration(
        rule,
        Path("/saved/caissa"),
        Path("/saved/selected.cai"),
        Path("/saved/openings.json"),
    )
    assert neural["pairs"] == 2000
    assert (
        neural["candidate"]["options"]["Lazy Neural"]
        is neural["opponent"]["options"]["Lazy Neural"]
        is True
    )
    full_actor_options(neural["candidate"], neural["opponent"], rule, True)
    for index in range(3):
        external = configuration(
            rule,
            Path("/saved/caissa"),
            Path("/saved/selected.cai"),
            Path("/saved/openings.json"),
            (index, Path("/saved/stockfish")),
        )
        assert external["candidate"] == neural["candidate"] and external["opponent"][
            "options"
        ] == external_options(index, rule["matches"])
    controls = []
    for case in [
        "proposal",
        "changed-engine",
        "changed-network",
        "changed-checkpoint",
        "different-learning-receipt",
        "different-independent-learning",
        "changed-mixture",
        "changed-wire",
        "weaker-classical",
        "reduced-neural",
        "reduced-external",
        "weaker-gain",
        "lower-bound",
        "bool-threads",
        "more-wall",
        "more-active",
        "renew-parent",
        "new-output",
        "changed-heldout",
        "test-selection",
    ]:
        current = copy.deepcopy(rule)
        if case == "proposal":
            current["status"] = "proposed"
        elif case in [
            "changed-engine",
            "changed-network",
            "changed-checkpoint",
            "different-learning-receipt",
            "different-independent-learning",
            "changed-heldout",
        ]:
            field = {
                "changed-engine": "engine_sha256",
                "changed-network": "network_sha256",
                "changed-checkpoint": "checkpoint_sha256",
                "different-learning-receipt": "original_model_campaign_sha256",
                "different-independent-learning": "original_independent_learning_sha256",
                "changed-heldout": "openings_sha256",
            }[case]
            current["strength_actor"][field] = "0" * 64
        elif case == "changed-mixture":
            current["network"]["neural_weight"] = 11
        elif case == "changed-wire":
            current["network"]["scale"] = 1024
        elif case == "weaker-classical":
            current["classical_control"] = "different baseline"
        elif case == "reduced-neural":
            current["matches"]["neural_pairs"] = 1999
        elif case == "reduced-external":
            current["matches"]["external_pairs"][0] = 333
        elif case == "weaker-gain":
            current["matches"]["minimum_neural_gain_elo"] = 49
        elif case == "lower-bound":
            current["matches"]["minimum_neural_lower_elo_exclusive"] = -1
        elif case == "bool-threads":
            current["matches"]["threads"] = True
        elif case == "more-wall":
            current["strength_resources"]["maximum_wall_seconds_per_domain"] += 1
        elif case == "more-active":
            current["strength_resources"]["maximum_active_seconds_per_domain"] += 1
        elif case == "renew-parent":
            current["strength_resources"]["parent_project_deadline_unix"] += 1
        elif case == "new-output":
            current["strength_resources"]["scope_paths"][
                "neural"
            ] = "runs/renamed-neural-budget"
        elif case == "test-selection":
            current["selection"] = "choose the strongest match seed"
        atomic(path, current)
        try:
            frozen_profile(path, sha(path), root)
        except ValueError as error:
            controls.append({"case": case, "reason": str(error)})
        else:
            raise AssertionError("v4 rehashed profile admitted " + case)
    if derivation is not None:
        copied = output / "changed-model"
        shutil.copytree(
            model / "selection",
            copied / "selection",
            ignore=shutil.ignore_patterns("*.pt", "*.cai"),
        )
        shutil.copy2(model / "MODEL_CAMPAIGN.json", copied / "MODEL_CAMPAIGN.json")
        current = json.loads((copied / "MODEL_CAMPAIGN.json").read_text())
        current["engine_sha256"] = rule["strength_actor"]["engine_sha256"]
        atomic(copied / "MODEL_CAMPAIGN.json", current)
        try:
            lineage(root, copied, engine, network, rule, commit)
        except ValueError as error:
            controls.append(
                {"case": "forged-new-learning-receipt", "reason": str(error)}
            )
        else:
            raise AssertionError("rewritten old learning receipt admitted")
    # Real locks exercise all four named owner paths and the process-wide lock.
    lockroot = output / "locks"
    lockroot.mkdir()
    for name in [
        "full-neural-strength-v3/OWNER.lock",
        "full-external-strength-v3/OWNER.lock",
        "full-neural-strength-v4/OWNER.lock",
        "full-external-strength-v4/OWNER.lock",
        "TIMED_STRENGTH.lock",
    ]:
        p = lockroot / name
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("a") as lock:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            try:
                avoid_decisive_matches(lockroot)
            except ValueError as error:
                controls.append({"case": "owner-lock-" + name, "reason": str(error)})
            else:
                raise AssertionError("held timed owner lock admitted")
    atomic(
        output / "CONTROLS.json",
        {
            "status": "passed",
            "controls": controls,
            "real_lineage_checked": derivation is not None,
            "full_acceptance": False,
            "scope": "No training or timed match was started",
        },
    )
    print(
        json.dumps(
            {
                "status": "passed",
                "controls": len(controls),
                "real_lineage_checked": derivation is not None,
                "full_acceptance": False,
            }
        )
    )


if __name__ == "__main__":
    main()
