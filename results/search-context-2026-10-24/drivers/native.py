import hashlib
import json
import os
import sys
import time
from pathlib import Path

from tools.campaign_process import Campaign, atomic

root = Path.cwd()
paths = ["CMakeLists.txt", "include/caissa/position.hpp", "src/position.cpp", "src/movegen.cpp", "tests/search_context_test.cpp"]
inputs = {path: hashlib.sha256((root / path).read_bytes()).hexdigest() for path in paths}
output = root / "runs/search-context-core"
os.environ["PATH"] = "/opt/homebrew/bin:" + os.environ.get("PATH", "")
if output.exists():
    first = json.loads((output / "COMMANDS.jsonl").read_text().splitlines()[0])
    deadline = first["utc_unix"] + 1800
    remaining = deadline - time.time()
    output = output / "attempt-2-path-recovery"
else:
    remaining = 1800
    deadline = time.time() + 1800
campaign = Campaign(output, {"inputs": inputs, "scope": "incremental reversible-history search identity; original teacher and old failures unchanged", "original_cumulative_deadline_unix": deadline}, remaining, absolute_deadline=deadline)
try:
    for name, directory, flags in [
        ("release", "build-search-context", ["-DCMAKE_BUILD_TYPE=Release"]),
        ("sanitizers", "build-search-context-sanitize", ["-DCMAKE_BUILD_TYPE=Debug", "-DCAISSA_SANITIZE=ON"]),
    ]:
        campaign.run(name + "-configure", ["cmake", "-S", ".", "-B", directory, *flags], 90, cwd=root)
        campaign.run(name + "-build", ["cmake", "--build", directory, "-j2"], 360, cwd=root)
        campaign.run(name + "-tests", ["ctest", "--test-dir", directory, "--output-on-failure", "--timeout", "300", "-j2"], 600, cwd=root)
    after = {path: hashlib.sha256((root / path).read_bytes()).hexdigest() for path in paths}
    if inputs != after:
        raise ValueError("native inputs changed during campaign")
    atomic(output / "SOURCE_INPUTS.json", inputs)
    campaign.close("passed Release and ASan/UBSan native campaigns", {"new_context_transitions_per_build": 1000000})
except BaseException as error:
    campaign.close("failed", {"type": type(error).__name__, "error": str(error)})
    raise
