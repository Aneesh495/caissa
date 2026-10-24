"""Bounded subprocess stages for local scientific campaigns.

Owns only its newly created process group. Completion records actual exits,
resource use and output hashes; a timeout or output overflow is never success.
"""

import fcntl
import hashlib
import json
import math
import os
import re
import resource
import selectors
import signal
import subprocess
import time
from pathlib import Path


class StageFailure(RuntimeError):
    def __init__(self, record):
        self.record = record
        super().__init__(
            f"stage {record['stage']} failed: {record['reason']} (exit {record['exit']})"
        )


def atomic(path, value):
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w") as stream:
        json.dump(value, stream, separators=(",", ":"), allow_nan=False)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)
    directory = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


def group_signal(pid, signum):
    try:
        os.killpg(pid, signum)
    except ProcessLookupError:
        pass


class Campaign:
    def __init__(
        self,
        output,
        config,
        maximum_seconds,
        *,
        absolute_deadline=None,
        resource_guard=None,
    ):
        self.output = Path(output)
        if not math.isfinite(maximum_seconds) or not 0 < maximum_seconds <= 7 * 86400:
            raise ValueError("finite campaign duration is required")
        self.output.mkdir(parents=True, exist_ok=False)
        self.lock = (self.output / "WRITER.lock").open("a")
        fcntl.flock(self.lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        self.config = config
        self.start = time.monotonic()
        self.deadline = self.start + maximum_seconds
        self.wall_deadline = time.time() + maximum_seconds
        if absolute_deadline is not None:
            if not math.isfinite(absolute_deadline):
                raise ValueError("finite absolute deadline required")
            self.wall_deadline = min(self.wall_deadline, absolute_deadline)
        self.resource_guard = resource_guard
        self.sequence = 0
        self.closed = False
        self.interrupted = None
        self.previous_handlers = {}
        for signum in [signal.SIGINT, signal.SIGTERM]:
            self.previous_handlers[signum] = signal.signal(signum, self._interrupt)
        atomic(self.output / "CONFIG.json", config)
        self._event(
            {
                "event": "campaign-started",
                "utc_unix": time.time(),
                "maximum_seconds": maximum_seconds,
            }
        )

    def _interrupt(self, signum, frame):
        self.interrupted = signum

    def _event(self, record):
        with (self.output / "COMMANDS.jsonl").open("a") as stream:
            stream.write(
                json.dumps(record, separators=(",", ":"), allow_nan=False) + "\n"
            )
            stream.flush()
            os.fsync(stream.fileno())

    def run(
        self,
        stage,
        command,
        timeout,
        maximum_output_bytes=32 * 1024 * 1024,
        *,
        cwd=None,
    ):
        if self.closed:
            raise ValueError("campaign already closed")
        if not re.fullmatch("[a-zA-Z0-9][a-zA-Z0-9_.-]{0,79}", stage):
            raise ValueError("invalid stage identity")
        if not command or not all(
            isinstance(arg, str) and "\0" not in arg for arg in command
        ):
            raise ValueError("explicit argument vector required")
        if (
            not math.isfinite(timeout)
            or not 0 < timeout <= 86400
            or not 1024 <= maximum_output_bytes <= 1024**3
        ):
            raise ValueError("stage resource bounds exceeded")
        if self.interrupted is not None:
            raise InterruptedError("campaign interrupted before stage start")
        if time.monotonic() >= self.deadline or time.time() >= self.wall_deadline:
            raise TimeoutError("cumulative campaign deadline exhausted")
        path = self.output / (stage + ".log")
        if path.exists():
            raise ValueError("stage log already exists")
        self.sequence += 1
        started = time.monotonic()
        wall_started = time.time()
        cpu_before = resource.getrusage(resource.RUSAGE_CHILDREN)
        deadline = min(started + timeout, self.deadline)
        wall_deadline = min(wall_started + timeout, self.wall_deadline)
        self._event(
            {
                "event": "stage-started",
                "stage": stage,
                "sequence": self.sequence,
                "command": command,
                "utc_unix": wall_started,
                "timeout_seconds": timeout,
                "maximum_output_bytes": maximum_output_bytes,
            }
        )
        process = None
        reason = None
        stopping = None
        parent_exited = None
        retained = 0
        discarded = 0
        last_progress = 0
        selector = selectors.DefaultSelector()
        try:
            with path.open("xb") as log:
                process = subprocess.Popen(
                    command,
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    bufsize=0,
                    start_new_session=True,
                    cwd=cwd,
                )
                os.set_blocking(process.stdout.fileno(), False)
                selector.register(process.stdout, selectors.EVENT_READ)
                while True:
                    now = time.monotonic()
                    if (
                        now >= deadline or time.time() >= wall_deadline
                    ) and reason is None:
                        reason = (
                            "campaign-timeout"
                            if deadline == self.deadline
                            or wall_deadline == self.wall_deadline
                            else "stage-timeout"
                        )
                    if self.interrupted is not None and reason is None:
                        reason = "signal-" + str(self.interrupted)
                    if process.poll() is not None and parent_exited is None:
                        parent_exited = now
                    if (
                        parent_exited is not None
                        and now - parent_exited > 2
                        and selector.get_map()
                        and reason is None
                    ):
                        reason = "descendant-retained-output-pipe"
                    if reason is not None and stopping is None:
                        stopping = now
                        group_signal(process.pid, signal.SIGTERM)
                    if stopping is not None and now - stopping >= 2:
                        group_signal(process.pid, signal.SIGKILL)
                    for key, _ in selector.select(0.1):
                        try:
                            block = os.read(key.fd, 65536)
                        except BlockingIOError:
                            continue
                        if not block:
                            selector.unregister(key.fileobj)
                            continue
                        room = maximum_output_bytes - retained
                        log.write(block[:room])
                        retained += min(room, len(block))
                        discarded += max(0, len(block) - room)
                        if discarded and reason is None:
                            reason = "output-byte-budget"
                    if now - last_progress >= 1:
                        if self.resource_guard is not None and reason is None:
                            try:
                                self.resource_guard()
                            except (ValueError, RuntimeError, OSError) as error:
                                reason = "resource-guard: " + str(error)
                        log.flush()
                        atomic(
                            self.output / "PROGRESS.json",
                            {
                                "phase": stage,
                                "pid": process.pid,
                                "command": command,
                                "seconds_this_stage": now - started,
                                "seconds_this_campaign": now - self.start,
                                "retained_output_bytes": retained,
                                "discarded_output_bytes": discarded,
                                "stopping_reason": reason,
                            },
                        )
                        last_progress = now
                    if process.poll() is not None and not selector.get_map():
                        break
                    if stopping is not None and now - stopping > 5:
                        reason = reason or "cleanup-timeout"
                        break
                if process.poll() is None:
                    group_signal(process.pid, signal.SIGKILL)
                exit_code = process.wait(timeout=5)
                log.flush()
                os.fsync(log.fileno())
        except BaseException as error:
            if process is not None:
                group_signal(process.pid, signal.SIGTERM)
                try:
                    process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    group_signal(process.pid, signal.SIGKILL)
                    process.wait(timeout=5)
            self._event(
                {
                    "event": "stage-exception",
                    "stage": stage,
                    "utc_unix": time.time(),
                    "exception": type(error).__name__,
                    "reason": str(error),
                }
            )
            raise
        finally:
            selector.close()
            if process is not None and process.stdout is not None:
                process.stdout.close()
            # A successful parent may leave background descendants after closing
            # stdout. They do not outlive the owned stage process group.
            if process is not None:
                group_signal(process.pid, signal.SIGTERM)
                end = time.monotonic() + 2
                while time.monotonic() < end:
                    try:
                        os.killpg(process.pid, 0)
                    except ProcessLookupError:
                        break
                    if reason is None:
                        reason = "leftover-descendant-process"
                    time.sleep(0.05)
                else:
                    group_signal(process.pid, signal.SIGKILL)
        cpu_after = resource.getrusage(resource.RUSAGE_CHILDREN)
        record = {
            "event": "stage-finished",
            "stage": stage,
            "sequence": self.sequence,
            "command": command,
            "exit": exit_code,
            "reason": reason or ("completed" if exit_code == 0 else "nonzero-exit"),
            "utc_start_unix": wall_started,
            "utc_end_unix": time.time(),
            "monotonic_seconds": time.monotonic() - started,
            "wall_seconds": time.time() - wall_started,
            "reaped_child_cpu_seconds": cpu_after.ru_utime
            + cpu_after.ru_stime
            - cpu_before.ru_utime
            - cpu_before.ru_stime,
            "retained_output_bytes": retained,
            "discarded_output_bytes": discarded,
            "log": path.name,
            "log_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        }
        self._event(record)
        atomic(self.output / (stage + ".json"), record)
        if exit_code != 0 or reason is not None:
            raise StageFailure(record)
        return record

    def close(self, status, details=None):
        if self.closed:
            return
        self.closed = True
        result = {
            "status": status,
            "details": details,
            "seconds_this_campaign": time.monotonic() - self.start,
            "stages_started": self.sequence,
            "utc_unix": time.time(),
            "full_acceptance": False,
        }
        atomic(self.output / "CAMPAIGN.json", result)
        self._event({"event": "campaign-finished", **result})
        for signum, previous in self.previous_handlers.items():
            signal.signal(signum, previous)
        self.lock.close()
