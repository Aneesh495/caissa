"""Scheduling controls, not substitute corpus, learning, or strength evidence."""

import copy
import contextlib
import fcntl
import hashlib
import json
import os
import tempfile
import time
from types import SimpleNamespace
from pathlib import Path
from unittest.mock import patch

from tools import continue_project as owner
from tools.campaign_process import StageFailure


def main():
    results = []

    def rejects(label, operation, reason):
        try:
            operation()
        except ValueError as error:
            assert reason in str(error), (label, str(error))
            results.append({"case": label, "reason": str(error)})
        else:
            raise AssertionError("invalid continuation admitted: " + label)

    draft = {"data": {"finalization_protocol_sha256": "a" * 64}}
    receipt = {
        "status": "passed full original-data finalization and independent reconstruction",
        "protocol_sha256": "a" * 64,
        "dataset_sha256": "b" * 64,
        "independent": {"profile": "full-data-replay"},
    }
    owner.finalized(draft, receipt, "b" * 64)
    for field, value in [
        ("status", "exported"),
        ("protocol_sha256", "c" * 64),
        ("dataset_sha256", "c" * 64),
        ("independent", {"profile": "pilot"}),
    ]:
        changed = copy.deepcopy(receipt)
        changed[field] = value
        rejects(
            "data-" + field,
            lambda: owner.finalized(draft, changed, "b" * 64),
            "complete independent pass",
        )
    with tempfile.TemporaryDirectory(prefix="caissa-continuation-controls-") as folder:
        root = Path(folder)
        path = root / "RECEIPT.json"
        completed = {
            "status": "completed planned model domain campaign",
            "protocol_sha256": "d" * 64,
            "failed_domains": [],
            "full_acceptance": False,
            "seeds": [17, 41, 73],
            "updates_per_seed": 20000,
            "test_model_metrics_used_for_selection": False,
        }

        def save(value):
            path.write_text(json.dumps(value) + "\n")

        save(completed)
        assert owner.completion("model", path, "d" * 64, 0) == completed
        for field, value in [
            ("updates_per_seed", 19999),
            ("seeds", [17, 41]),
            ("test_model_metrics_used_for_selection", True),
        ]:
            changed = copy.deepcopy(completed)
            changed[field] = value
            save(changed)
            rejects(
                "model-" + field,
                lambda: owner.completion("model", path, "d" * 64),
                "three complete seeds",
            )
        changed = copy.deepcopy(completed)
        changed["status"] += " with failed gates"
        changed["failed_domains"] = ["G07 retained negative learning endpoint"]
        save(changed)
        assert (
            owner.completion("model", path, "d" * 64, 2)["failed_domains"]
            == changed["failed_domains"]
        )
        rejects(
            "failed-domain-exit-zero",
            lambda: owner.completion("model", path, "d" * 64, 0),
            "exit differs",
        )
        changed["failed_domains"] = []
        save(changed)
        rejects(
            "failed-status-empty-failures",
            lambda: owner.completion("model", path, "d" * 64),
            "failure flags disagree",
        )
        changed = copy.deepcopy(completed)
        changed["full_acceptance"] = True
        save(changed)
        rejects(
            "domain-cannot-claim-release",
            lambda: owner.completion("model", path, "d" * 64),
            "complete matching receipt",
        )
        save(completed)
        rejects(
            "crash-cannot-be-negative-endpoint",
            lambda: owner.completion("model", path, "d" * 64, -15),
            "exit differs",
        )
        rejects(
            "different-protocol",
            lambda: owner.completion("model", path, "e" * 64),
            "complete matching receipt",
        )
        strength = {
            "status": "completed fixed full strength sample with failed gate",
            "protocol_sha256": "d" * 64,
            "failed_domains": ["G08 retained negative contribution"],
            "full_acceptance": False,
        }
        save(strength)
        assert owner.completion("strength", path, "d" * 64, 2) == strength
        results.append(
            {
                "case": "actual-negative-domain-continues",
                "reason": "valid completed negative receipts retain their failed domains",
            }
        )
        original = root / "original-owner"
        original.mkdir()
        command = owner.archived_command("tools.full_learning", ["--resume"], original)
        assert command[1] == "-P" and command[4] == str(Path.cwd())
        (original / "SCOPE.json").write_text("{}")
        rejects(
            "missing-original-archive",
            lambda: owner.archived_command("tools.full_learning", [], original),
            "original owner source",
        )
        (original / "source").mkdir()
        command = owner.archived_command("tools.full_learning", ["--resume"], original)
        assert (
            command[4] == str((original / "source").resolve())
            and command[-1] == "--resume"
        )
        results.append(
            {
                "case": "resume-imports-archived-owner",
                "reason": "safe module launcher selects original source rather than current root",
            }
        )

        data = root / "data-owner"
        data.mkdir()
        output = root / "continuation"
        output.mkdir()
        (data / "INDEPENDENT_PROGRESS.json").write_text('{"completed_games":256}\n')
        with patch.object(owner, "DATA", data):
            rejects(
                "stopped-dependency",
                lambda: owner.wait_for_data(time.time() + 30, output),
                "data owner stopped",
            )
            with (data / "OWNER.lock").open("a") as lock:
                fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)

                def finish(seconds):
                    assert 0 < seconds <= 15
                    assert not (root / "model").exists()
                    (data / "FINALIZATION.json").write_text(json.dumps(receipt))

                with patch.object(owner.time, "sleep", side_effect=finish):
                    owner.wait_for_data(time.time() + 30, output)
                observed = json.loads((output / "PROGRESS.json").read_text())
                assert observed["observed"]["completed_games"] == 256
                results.append(
                    {
                        "case": "live-dependency-waits",
                        "reason": "existing owner retains its lock; actual counters are published; no model scope starts",
                    }
                )
            (data / "FINALIZATION.json").unlink()
            rejects(
                "scheduler-deadline-exhausted",
                lambda: owner.wait_for_data(time.time() - 1, output),
                "wall ceiling exhausted",
            )
        initial_cwd = Path.cwd()
        for scenario in ("completed-negative-endpoints", "unexpected-crash"):
            workspace = root / scenario
            workspace.mkdir()
            os.chdir(workspace)
            try:
                data = workspace / "data-replay"
                data.mkdir()
                (data / "SCOPE.json").write_text('{"original_scope":"immutable"}')
                stockfish = workspace / "comparator-fixture"
                stockfish.write_bytes(b"synthetic unexecuted comparator input")
                draft_path = workspace / "DRAFT.json"
                draft_path.write_text(
                    json.dumps(
                        {
                            "matches": {
                                "stockfish_sha256": hashlib.sha256(
                                    stockfish.read_bytes()
                                ).hexdigest()
                            }
                        }
                    )
                )
                calls = []

                class FakeCampaign:
                    def __init__(self, output, *args, **kwargs):
                        output.mkdir(parents=True, exist_ok=False)

                    def run(self, name, command, active, **kwargs):
                        calls.append(name)
                        if scenario == "unexpected-crash":
                            raise StageFailure(
                                {"exit": 9, "reason": "nonzero-exit", "stage": name}
                            )
                        failed = name != "full-external"
                        if name == "full-model":
                            value = copy.deepcopy(completed)
                            value["status"] += " with failed gates"
                            value["failed_domains"] = ["G07 retained failure"]
                            target = owner.MODEL / "MODEL_CAMPAIGN.json"
                        else:
                            value = {
                                "status": "completed fixed full strength sample",
                                "failed_domains": [],
                                "protocol_sha256": "d" * 64,
                                "full_acceptance": False,
                            }
                            if failed:
                                value["status"] += " with failed gate"
                                value["failed_domains"] = ["G08 retained failure"]
                            target = Path(
                                "runs/" + name + "-strength-v3/STRENGTH_CAMPAIGN.json"
                            )
                        target.parent.mkdir(parents=True, exist_ok=True)
                        target.write_text(json.dumps(value))
                        if failed:
                            raise StageFailure(
                                {"exit": 2, "reason": "nonzero-exit", "stage": name}
                            )

                    def close(self, *args, **kwargs):
                        pass

                with contextlib.ExitStack() as stack:
                    for name, value in {
                        "DATA": data,
                        "DRAFT": draft_path,
                        "OUTPUT": workspace / "scheduler",
                        "MODEL": workspace / "model",
                        "DATASET": workspace / "dataset",
                        "Campaign": FakeCampaign,
                    }.items():
                        stack.enter_context(patch.object(owner, name, value))
                    stack.enter_context(
                        patch.object(owner, "wait_for_data", return_value=None)
                    )
                    stack.enter_context(
                        patch.object(owner, "freeze", return_value=({}, "d" * 64))
                    )
                    stack.enter_context(
                        patch.object(owner, "source_files", return_value=[])
                    )
                    stack.enter_context(
                        patch.object(owner, "archive_source", return_value=None)
                    )
                    stack.enter_context(
                        patch.object(
                            owner.subprocess,
                            "check_output",
                            side_effect=lambda command, **kwargs: (
                                "" if command[1] == "status" else "f" * 40
                            ),
                        )
                    )
                    arguments = SimpleNamespace(resume=False, stockfish=stockfish)
                    if scenario == "unexpected-crash":
                        rejects(
                            "abnormal-child-stops-queue",
                            lambda: owner.execute(arguments),
                            "domain did not finish",
                        )
                        assert (
                            calls == ["full-model"]
                            and (owner.OUTPUT / "FAILED.json").exists()
                        )
                        assert not (owner.OUTPUT / "CONTINUATION.json").exists()
                    else:
                        owner.execute(arguments)
                        assert calls == ["full-model", "full-neural", "full-external"]
                        result = json.loads(
                            (owner.OUTPUT / "CONTINUATION.json").read_text()
                        )
                        assert result["failed_domains"] == [
                            "G07 retained failure",
                            "G08 retained failure",
                        ]
                        assert (
                            result["full_acceptance"] is False
                            and result["absolute_elo"] is None
                        )
                        results.append(
                            {
                                "case": "negative-learning-still-measures-strength",
                                "reason": "both predeclared strength domains execute in order and both failed gates remain failed",
                            }
                        )
                    scope = json.loads((owner.OUTPUT / "SCOPE.json").read_text())
                    scope["origin_unix"] = time.time() - owner.MAXIMUM_WALL_SECONDS - 10
                    scope["deadline_unix"] = (
                        scope["origin_unix"] + owner.MAXIMUM_WALL_SECONDS
                    )
                    (owner.OUTPUT / "SCOPE.json").write_text(json.dumps(scope))
                    retained = (owner.OUTPUT / "SCOPE.json").read_bytes()
                    arguments.resume = True
                    rejects(
                        "expired-queue-not-reset-" + scenario,
                        lambda: owner.execute(arguments),
                        "original continuation wall ceiling",
                    )
                    assert (owner.OUTPUT / "SCOPE.json").read_bytes() == retained
            finally:
                os.chdir(initial_cwd)
    print(
        json.dumps(
            {
                "status": "passed",
                "controls": results,
                "full_acceptance": False,
                "scope": "Scheduling and receipt controls only; all positive test-domain receipts are synthetic fixtures",
            }
        )
    )


if __name__ == "__main__":
    main()
