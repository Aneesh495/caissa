"""Exercise actual exit, flood, timeout and descendant cleanup paths."""

import argparse
import json
import subprocess
import sys
from pathlib import Path
from tools.campaign_process import Campaign, StageFailure

parser = argparse.ArgumentParser()
parser.add_argument("--engine", default="build-lto/caissa")
parser.add_argument("--output", type=Path, required=True)
a = parser.parse_args()
runner = Campaign(a.output, {"profile": "synthetic process controls"}, 60)
records = []
try:
    records.append(runner.run("native-version", [a.engine, "--version"], 10))
    cases = [
        (
            "nonzero",
            [sys.executable, "-c", "raise SystemExit(7)"],
            3,
            4096,
            "nonzero-exit",
        ),
        (
            "output-flood",
            [sys.executable, "-c", 'import os;os.write(1,b"x"*1000000)'],
            3,
            4096,
            "output-byte-budget",
        ),
        (
            "ignored-termination",
            [
                sys.executable,
                "-c",
                "import signal,time;signal.signal(signal.SIGTERM,signal.SIG_IGN);time.sleep(30)",
            ],
            0.2,
            4096,
            "stage-timeout",
        ),
    ]
    for name, command, timeout, cap, expected in cases:
        try:
            runner.run(name, command, timeout, cap)
        except StageFailure as failure:
            if failure.record["reason"] != expected:
                raise ValueError("wrong process failure classification")
            records.append(failure.record)
        else:
            raise ValueError("failed child was accepted: " + name)
        assert (a.output / (name + ".log")).stat().st_size <= cap
    pid_path = a.output / "descendant.pid"
    child = (
        "import signal,time;signal.signal(signal.SIGTERM,signal.SIG_IGN);time.sleep(30)"
    )
    parent = 'import pathlib,subprocess,sys;child=subprocess.Popen([sys.executable,"-c",sys.argv[2]],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL);pathlib.Path(sys.argv[1]).write_text(str(child.pid))'
    try:
        runner.run(
            "leftover-descendant",
            [sys.executable, "-c", parent, str(pid_path), child],
            5,
        )
    except StageFailure as failure:
        assert failure.record["reason"] == "leftover-descendant-process"
        records.append(failure.record)
    else:
        raise ValueError("unowned running descendant was accepted")
    result = subprocess.run(
        ["ps", "-p", pid_path.read_text(), "-o", "stat="],
        capture_output=True,
        text=True,
    )
    assert not result.stdout.strip() or result.stdout.strip().startswith("Z")
    runner.close("passed-synthetic-controls", {"records": len(records)})
except BaseException as error:
    runner.close("failed", str(error))
    raise
print(
    json.dumps(
        {
            "status": "passed",
            "controls": len(records),
            "scope": "synthetic process lifecycle plus actual native version",
            "full_acceptance": False,
        }
    )
)
