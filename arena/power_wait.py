"""Opt-in AC waiting before native work, without pausing an active search clock."""

import json
import math
import subprocess
import threading
import time
from pathlib import Path

from tools.campaign_process import atomic
from tools.power_guard import observe


class PowerWait:
    def __init__(self, output, policy, *, clock=None, sleeper=None, observer=None):
        self.output = Path(output)
        self.clock = clock or time.time
        self.sleep = sleeper or time.sleep
        self.observe = observer or observe
        if (
            not isinstance(policy, dict)
            or set(policy) != {"mode", "deadline_unix"}
            or policy["mode"] != "wait-between-moves-v1"
            or type(policy["deadline_unix"]) not in (int, float)
            or not math.isfinite(policy["deadline_unix"])
            or not self.clock() < policy["deadline_unix"] <= self.clock() + 7 * 86400
        ):
            raise ValueError("finite prospective power wait policy required")
        self.policy = dict(policy)
        self.deadline = policy["deadline_unix"]
        path = self.output / "POWER_WAIT_POLICY.json"
        if path.exists():
            if path.is_symlink() or json.loads(path.read_text()) != policy:
                raise ValueError("original power wait policy or deadline changed")
        else:
            atomic(path, policy)
        self.lock = threading.Lock()
        self.last = -math.inf
        self.ac = False
        self.wait_started = None
        self.waited = 0.0
        progress = self.output / "POWER_WAIT_PROGRESS.json"
        if progress.exists():
            if progress.is_symlink() or progress.stat().st_size > 65536:
                raise ValueError("invalid saved power wait progress")
            saved = json.loads(progress.read_text())
            if (
                saved["deadline_unix"] != self.deadline
                or saved["state"] == "deadline-exhausted"
            ):
                raise ValueError("saved power wait deadline exhausted or changed")
            self.waited = saved["waited_seconds"]
            if (
                type(self.waited) not in (int, float)
                or not math.isfinite(self.waited)
                or self.waited < 0
            ):
                raise ValueError("invalid cumulative power wait duration")
            if saved["state"] == "waiting-for-ac":
                self.wait_started = saved["unix"]

    def record(self, state, **extra):
        row = {
            "state": state,
            "unix": self.clock(),
            "deadline_unix": self.deadline,
            "waited_seconds": self.waited,
            **extra,
        }
        atomic(self.output / "POWER_WAIT_PROGRESS.json", row)
        path = self.output / "POWER_WAIT_EVENTS.jsonl"
        if path.is_symlink() or (path.exists() and not path.is_file()):
            raise ValueError("power wait journal must be a regular file")
        if path.exists() and path.stat().st_size > 4 * 1024 * 1024:
            raise ValueError("power wait event ceiling exhausted")
        with path.open("a") as stream:
            stream.write(json.dumps(row, separators=(",", ":")) + "\n")
            stream.flush()

    def before_work(self, *, force=False):
        """Return on observed AC; real deadline continues throughout waiting."""
        with self.lock:
            if force:
                self.last = -math.inf
            while True:
                now = self.clock()
                if now >= self.deadline:
                    if self.wait_started is not None:
                        self.waited += now - self.wait_started
                        self.wait_started = None
                    self.record("deadline-exhausted")
                    raise ValueError("power wait reached original deadline")
                if now - self.last >= 1:
                    try:
                        self.ac = self.observe()["ac_power"] is True
                    except (
                        ValueError,
                        OSError,
                        TimeoutError,
                        subprocess.TimeoutExpired,
                    ):
                        self.ac = False
                    self.last = self.clock()
                if self.ac and self.clock() < self.deadline:
                    if self.wait_started is not None:
                        self.waited += self.clock() - self.wait_started
                        self.record("resumed-on-ac")
                        self.wait_started = None
                    return
                if self.wait_started is None:
                    self.wait_started = self.clock()
                    self.record("waiting-for-ac")
                self.sleep(min(1, max(0, self.deadline - self.clock())))
