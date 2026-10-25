"""Power admission refuses battery before budget creation; assertions are scoped."""

import json
import tempfile
from pathlib import Path
from unittest.mock import Mock, patch

from tools.power_guard import POLICY, BATTERY_POLICY, PowerGuard


def main():
    results = []
    with patch("tools.power_guard.sys.platform", "darwin"):
        with patch("tools.power_guard.observe", return_value={"ac_power": False}):
            try:
                PowerGuard(POLICY)
            except ValueError as error:
                assert "AC power" in str(error)
                results.append("battery refused before creating a scope")
            else:
                raise AssertionError("battery host admitted")
        helper = Mock()
        helper.poll.return_value = None
        with tempfile.TemporaryDirectory(prefix="caissa-power-controls-") as folder:
            with (
                patch(
                    "tools.power_guard.observe",
                    return_value={
                        "ac_power": True,
                        "stdout": "synthetic AC",
                        "stderr": "",
                        "unix": 0,
                    },
                ),
                patch(
                    "tools.power_guard.subprocess.Popen", return_value=helper
                ) as process,
            ):
                guard = PowerGuard(POLICY)
                guard.start(Path(folder))
                assert process.call_args.args[0][0:3] == [
                    "/usr/bin/caffeinate",
                    "-dis",
                    "-w",
                ]
                guard.last = -1e9
                with patch(
                    "tools.power_guard.observe",
                    return_value={
                        "ac_power": False,
                        "stdout": "synthetic battery",
                        "stderr": "",
                        "unix": 1,
                    },
                ):
                    try:
                        guard.check()
                    except ValueError as error:
                        assert "same deadline" in str(error)
                        results.append(
                            "AC loss stops work without granting a new deadline"
                        )
                    else:
                        raise AssertionError("AC loss ignored")
                guard.close()
                helper.terminate.assert_called_once()
                results.append("awake assertion terminates with its owner")
    with patch("tools.power_guard.observe") as query:
        PowerGuard(None).check()
        query.assert_not_called()
        results.append("legacy frozen protocols retain original power behavior")
    helper = Mock()
    helper.poll.return_value = None
    with (
        tempfile.TemporaryDirectory(prefix="caissa-battery-controls-") as folder,
        patch("tools.power_guard.sys.platform", "darwin"),
        patch(
            "tools.power_guard.observe",
            return_value={
                "ac_power": False,
                "stdout": "synthetic battery",
                "stderr": "",
                "unix": 0,
            },
        ),
        patch("tools.power_guard.subprocess.Popen", return_value=helper) as process,
    ):
        guard = PowerGuard(BATTERY_POLICY)
        guard.start(Path(folder))
        assert process.call_args.args[0][1] == "-di"
        guard.close()
        results.append(
            "continued-work policy admits battery with a scoped awake assertion"
        )
    print(
        json.dumps({"status": "passed", "controls": results, "full_acceptance": False})
    )


if __name__ == "__main__":
    main()
