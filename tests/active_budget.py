"""Wall sleep allowance cannot reset the cumulative active budget on restart."""

import json
import tempfile
import sys
from pathlib import Path
from unittest.mock import patch

from tools.recovery_scope import RecoveryScope
from tools.campaign_process import Campaign


def main():
    with tempfile.TemporaryDirectory(prefix="caissa-active-budget-") as folder:
        base = Path(folder)
        data = base / "data"
        data.mkdir()
        with (
            patch("tools.recovery_scope.time.time", return_value=1000),
            patch("tools.recovery_scope.time.monotonic", return_value=100),
        ):
            scope = RecoveryScope(
                base / "scope",
                {"frozen": "input"},
                86400,
                data,
                0,
                1,
                maximum_authorized_seconds=86400,
                maximum_active_seconds=30,
            )
        with (
            patch("tools.recovery_scope.time.time", return_value=20000),
            patch("tools.recovery_scope.time.monotonic", return_value=110),
        ):
            assert 19 < scope.remaining() <= 20
            scope.close()
        with (
            patch("tools.recovery_scope.time.time", return_value=21000),
            patch("tools.recovery_scope.time.monotonic", return_value=200),
        ):
            resumed = RecoveryScope(
                base / "scope",
                {"frozen": "input"},
                86400,
                data,
                0,
                1,
                resume=True,
                maximum_authorized_seconds=86400,
                maximum_active_seconds=30,
            )
            assert 19 < resumed.remaining() <= 20
        with (
            patch("tools.recovery_scope.time.time", return_value=21001),
            patch("tools.recovery_scope.time.monotonic", return_value=221),
        ):
            try:
                resumed.check()
            except TimeoutError:
                pass
            else:
                raise AssertionError("resumed active budget was reset")
            resumed.close()
        ledger = json.loads((base / "scope/ACTIVE_USAGE.json").read_text())
        assert ledger["active_seconds"] == 31 and ledger["closed"] is True
        with patch("tools.campaign_process.time.time", return_value=1000):
            campaign = Campaign(
                base / "separate-clocks",
                {"scope": "synthetic wall jump"},
                2,
                maximum_wall_seconds=100,
            )
        with patch("tools.campaign_process.time.time", return_value=1010):
            record = campaign.run(
                "after-sleep", [sys.executable, "-c", "pass"], 1, wall_timeout=90
            )
            assert record["exit"] == 0
            campaign.close("passed separate wall/active clock control")
    print(
        json.dumps(
            {
                "status": "passed",
                "wall_sleep_does_not_consume_active_allowance": True,
                "resume_preserves_used_active_time": True,
                "exhausted_active_budget_refused": True,
                "full_acceptance": False,
            }
        )
    )


if __name__ == "__main__":
    main()
