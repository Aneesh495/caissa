"""A denied final signal must retain timeout/nonzero evidence and fail closed."""

import json
import signal
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

from tools.campaign_process import Campaign, StageFailure, group_signal


def main():
    observations = []
    with tempfile.TemporaryDirectory(prefix="caissa-cleanup-controls-") as name:
        root = Path(name)
        campaign = Campaign(
            root / "campaign", {"scope": "synthetic final signal denial"}, 30
        )
        try:
            for label, code, timeout, expected in [
                ("successful-parent", "pass", 2, "cleanup-permission-denied"),
                ("failed-parent", "raise SystemExit(7)", 2, "nonzero-exit"),
                ("timed-parent", "import time;time.sleep(30)", 0.1, "stage-timeout"),
            ]:
                count = 0

                def deny_cleanup(pid, signum):
                    nonlocal count
                    count += 1
                    if label == "timed-parent" and count == 1:
                        return group_signal(pid, signum)
                    raise PermissionError("synthetic denied final signal")

                with patch(
                    "tools.campaign_process.group_signal", side_effect=deny_cleanup
                ):
                    try:
                        campaign.run(label, [sys.executable, "-c", code], timeout)
                    except StageFailure as error:
                        record = error.record
                        assert record["reason"] == expected, (label, record)
                        assert record["cleanup_warnings"] and record["exit"] == (
                            0
                            if label == "successful-parent"
                            else 7 if label == "failed-parent" else -signal.SIGTERM
                        )
                        observations.append(
                            {
                                "case": label,
                                "actual_exit": record["exit"],
                                "retained_reason": record["reason"],
                                "cleanup_warnings": record["cleanup_warnings"],
                            }
                        )
                    else:
                        raise AssertionError("signal denial was silently accepted")
            campaign.close("passed synthetic cleanup denial controls")
        finally:
            campaign.close("closed")
    print(
        json.dumps(
            {"status": "passed", "controls": observations, "full_acceptance": False}
        )
    )


if __name__ == "__main__":
    main()
