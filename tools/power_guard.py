"""Scoped awake-host admission for a separately authorized macOS recovery."""

import os
import json
import subprocess
import sys
import time

from tools.campaign_process import atomic

POLICY = {
    "platform": "darwin",
    "require_ac_power": True,
    "scoped_caffeinate_flags": "-dis",
    "check_interval_seconds": 5,
}
BATTERY_POLICY = {**POLICY, "require_ac_power": False, "scoped_caffeinate_flags": "-di"}
WAIT_POLICY = {**BATTERY_POLICY, "wait_at_native_work_boundaries": True}


def observe():
    result = subprocess.run(
        ["/usr/bin/pmset", "-g", "batt"], capture_output=True, text=True, timeout=3
    )
    if result.returncode or len(result.stdout) + len(result.stderr) > 16384:
        raise ValueError("could not establish bounded host power state")
    return {
        "unix": time.time(),
        "stdout": result.stdout,
        "stderr": result.stderr,
        "ac_power": result.stdout.splitlines()[0:1] == ["Now drawing from 'AC Power'"],
    }


class PowerGuard:
    def __init__(self, policy):
        self.policy = policy
        self.helper = None
        self.last = -1e9
        self.output = None
        if policy is not None:
            if (
                policy not in (POLICY, BATTERY_POLICY, WAIT_POLICY)
                or sys.platform != "darwin"
            ):
                raise ValueError("unsupported recovery awake-host policy")
            self.admission = observe()
            if policy["require_ac_power"] and not self.admission["ac_power"]:
                raise ValueError(
                    "plug Mac into AC power before starting the new recovery budget"
                )

    def start(self, output):
        self.output = output
        if self.policy is not None:
            atomic(output / "POWER_ADMISSION.json", self.admission)
            self.helper = subprocess.Popen(
                [
                    "/usr/bin/caffeinate",
                    self.policy["scoped_caffeinate_flags"],
                    "-w",
                    str(os.getpid()),
                ],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            self.check()

    def check(self):
        if self.policy is None or time.monotonic() - self.last < 5:
            return
        row = observe()
        if self.helper is None or self.helper.poll() is not None:
            raise ValueError("scoped recovery awake assertion exited")
        with (self.output / "POWER_SAMPLES.jsonl").open("a") as stream:
            stream.write(json.dumps(row, separators=(",", ":")) + "\n")
        self.last = time.monotonic()
        if self.policy["require_ac_power"] and not row["ac_power"]:
            raise ValueError(
                "recovery lost required AC power; preserve checkpoint and resume within the same deadline"
            )

    def close(self):
        if self.helper is not None and self.helper.poll() is None:
            self.helper.terminate()
            try:
                self.helper.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self.helper.kill()
                self.helper.wait(timeout=3)
