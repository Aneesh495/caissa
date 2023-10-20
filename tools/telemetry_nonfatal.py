"""Optional environment observations never decide whether a match can continue."""

import json
import subprocess
import threading
import time
from pathlib import Path

READ_ERRORS = (OSError, ValueError, subprocess.SubprocessError)


def power_or_unknown(observer):
    try:
        return observer()
    except READ_ERRORS as error:
        return {
            "unix": time.time(),
            "stdout": "",
            "stderr": "",
            "ac_power": None,
            "observation_available": False,
            "observer_error": type(error).__name__,
        }


def rows_or_unknown(observer):
    try:
        return observer(), None
    except READ_ERRORS as error:
        return [], type(error).__name__


def install(power_module, host_module, output):
    """Adapt a verified archived controller without editing its source files.

    Only read-only telemetry calls are wrapped. Scope, disk, lease, actor and
    protocol guards remain outside these handlers and keep their real failures.
    """
    output = Path(output)
    original_power, original_rows = power_module.observe, host_module.process_rows
    lock = threading.Lock()
    progress = output / "TELEMETRY_PROGRESS.json"
    counts = (
        json.loads(progress.read_text())["counts"]
        if progress.exists()
        else {"power": 0, "process-inventory": 0}
    )

    def record(kind, error):
        row = {
            "unix": time.time(),
            "observer": kind,
            "observation_available": False,
            "error_type": error,
        }
        with lock:
            counts[kind] += 1
            temporary = progress.with_suffix(".tmp")
            temporary.write_text(
                json.dumps({"counts": counts, "last": row}, separators=(",", ":"))
                + "\n"
            )
            temporary.replace(progress)
            path = output / "TELEMETRY_ERRORS.jsonl"
            # Keep a finite journal. Unknown-state counters remain visible even
            # after the detail ceiling, with no fabricated power or CPU values.
            if not path.exists() or path.stat().st_size < 4 * 1024 * 1024:
                with path.open("a") as stream:
                    stream.write(json.dumps(row, separators=(",", ":")) + "\n")
                    stream.flush()

    def power():
        row = power_or_unknown(original_power)
        if row.get("observation_available") is False:
            record("power", row["observer_error"])
        return row

    def processes():
        rows, error = rows_or_unknown(original_rows)
        if error is not None:
            record("process-inventory", error)
        return rows

    power_module.observe = power
    host_module.process_rows = processes
