"""Actual ownership, durable deadlines and resource-triggered child cleanup."""

import hashlib
import json
import tempfile
import time
import sys
from pathlib import Path
from unittest.mock import patch

from tools.campaign_process import Campaign, StageFailure
from tools.recovery_scope import RecoveryScope


def main():
    records = []
    with tempfile.TemporaryDirectory(prefix="caissa-recovery-controls-") as folder:
        root = Path(folder)
        data = root / "data"
        data.mkdir()
        (data / "original").write_bytes(b"original")
        scope = RecoveryScope(root / "scope", {"input": "frozen"}, 30, data, 0, 1)
        original = (scope.root / "SCOPE.json").read_bytes()
        deadline = scope.deadline
        try:
            RecoveryScope(
                root / "scope", {"input": "frozen"}, 30, data, 0, 1, resume=True
            )
        except BlockingIOError:
            records.append("second owner refused")
        else:
            raise AssertionError("duplicate owner admitted")
        scope.close()
        time.sleep(0.02)
        resumed = RecoveryScope(
            root / "scope", {"input": "frozen"}, 30, data, 0, 1, resume=True
        )
        assert (
            resumed.deadline == deadline
            and resumed.remaining() < 30
            and (resumed.root / "SCOPE.json").read_bytes() == original
        )
        resumed.close()
        records.append("same original deadline and immutable scope on resume")
        for label, bindings, seconds in [
            ("input-change", {"input": "changed"}, 30),
            ("budget-increase", {"input": "frozen"}, 60),
        ]:
            try:
                RecoveryScope(
                    root / "scope", bindings, seconds, data, 0, 1, resume=True
                )
            except ValueError:
                records.append(label + " refused")
            else:
                raise AssertionError(label + " admitted")
        with patch("tools.recovery_scope.time.time", return_value=deadline + 1):
            try:
                RecoveryScope(
                    root / "scope", {"input": "frozen"}, 30, data, 0, 1, resume=True
                )
            except TimeoutError:
                records.append("expired original scope refused")
            else:
                raise AssertionError("deadline reset")
        with patch("tools.recovery_scope.time.time", return_value=deadline - 40):
            try:
                RecoveryScope(
                    root / "scope", {"input": "frozen"}, 30, data, 0, 1, resume=True
                )
            except ValueError:
                records.append("wall-clock rollback refused")
            else:
                raise AssertionError("rollback extended deadline")
        tiny = RecoveryScope(root / "tiny", {}, 30, data, 0, 4096 / 1024**3)
        (data / "extra").write_bytes(b"x" * 8192)
        tiny.last_size_check = -float("inf")
        try:
            tiny.check()
        except ValueError:
            records.append("additional byte ceiling enforced")
        else:
            raise AssertionError("additional disk allocation accepted")
        tiny.close()

        def fail_resource():
            raise ValueError("known resource ceiling")

        runner = Campaign(
            root / "process",
            {"scope": "synthetic resource control"},
            10,
            resource_guard=fail_resource,
        )
        try:
            try:
                runner.run(
                    "resource-stop",
                    [sys.executable, "-c", "import time;time.sleep(30)"],
                    5,
                )
            except StageFailure as error:
                assert (
                    error.record["reason"] == "resource-guard: known resource ceiling"
                    and error.record["exit"] != 0
                )
                records.append("owned child reaped after resource stop")
            else:
                raise AssertionError("resource-stop child accepted")
            runner.close("passed synthetic resource stop")
        finally:
            runner.close("closed")
        runner = Campaign(
            root / "absolute",
            {"scope": "synthetic absolute deadline"},
            10,
            absolute_deadline=time.time() + 0.1,
        )
        try:
            try:
                runner.run(
                    "deadline-stop",
                    [sys.executable, "-c", "import time;time.sleep(30)"],
                    5,
                )
            except StageFailure as error:
                assert (
                    error.record["reason"] == "campaign-timeout"
                    and error.record["exit"] != 0
                )
                records.append("absolute deadline terminates and reaps child")
            else:
                raise AssertionError("absolute deadline ignored")
            runner.close("passed synthetic absolute deadline")
        finally:
            runner.close("closed")
    print(
        json.dumps({"status": "passed", "controls": records, "full_acceptance": False})
    )


if __name__ == "__main__":
    main()
