"""Fixed exact-option stop and instrumented-search observations, never games."""

import hashlib
import json
import os
from pathlib import Path
import re
import select
import subprocess
import time

from tools.campaign_process import atomic


class Journal:
    def __init__(self, path, quota):
        self.stream = Path(path).open("xb")
        # Pay for the whole bounded journal before any measured stop command.
        wanted = quota.spec["journal_limit_bytes"]
        self.stream.credit += quota.reserve("data", self.stream.key, wanted - self.stream.credit)
        self.hash = hashlib.sha256()
        self.frames = 0

    def emit(self, event, session, **fields):
        row = {"event": event, "session": session, **fields}
        raw = (json.dumps(row, separators=(",", ":"), allow_nan=False) + "\n").encode()
        self.stream.write(raw)
        self.hash.update(raw)
        self.frames += 1

    def close(self):
        self.stream.flush()
        os.fsync(self.stream.fileno())
        self.stream.close()


class Native:
    def __init__(self, scope, journal, index, kind, threads):
        self.scope, self.journal, self.index = scope, journal, index
        self.kind, self.threads = kind, threads
        self.buffer = {"stdout": bytearray(), "stderr": bytearray()}
        self.ready = []
        self.stderr_hash = hashlib.sha256()
        self.stderr_bytes = self.retained_stderr = self.dropped_stderr = 0
        self.critical = bytearray()
        self.runtime_seen = False
        self.closed = False
        env = dict(os.environ)
        for key in list(env):
            if key.startswith("DYLD_") or key in {"TSAN_OPTIONS", "ASAN_OPTIONS"}:
                env.pop(key)
        if kind == "instrumented":
            env.update(DYLD_LIBRARY_PATH=str(Path(scope["instrumented_runtime"]).parent), DYLD_PRINT_LIBRARIES="1", TSAN_OPTIONS="halt_on_error=1:exitcode=66")
        image = scope["release_engine"] if kind == "release" else scope["instrumented_engine"]
        self.process = subprocess.Popen([image], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env, bufsize=0)
        self.streams = {self.process.stdout: "stdout", self.process.stderr: "stderr"}
        self.journal.emit("open", index, kind=kind, threads=threads, engine_sha256=scope["engine_sha256"] if kind == "release" else scope["instrumented_engine_sha256"], runtime_sha256=None if kind == "release" else scope["instrumented_runtime_sha256"], network_sha256=scope["network_sha256"])

    def send(self, text):
        stamp = time.monotonic_ns()
        self.journal.emit("send", self.index, ns=stamp, text=text)
        self.process.stdin.write((text + "\n").encode())
        self.process.stdin.flush()
        return stamp

    def pump(self, timeout=0.1):
        if not self.streams:
            return
        readable, _, _ = select.select(list(self.streams), [], [], timeout)
        for stream in readable:
            channel = self.streams[stream]
            data = os.read(stream.fileno(), 65536)
            stamp = time.monotonic_ns()
            if not data:
                del self.streams[stream]
                if self.buffer[channel]:
                    raise ValueError("unterminated native output line")
                continue
            if channel == "stderr":
                self.stderr_hash.update(data)
                self.stderr_bytes += len(data)
            self.buffer[channel].extend(data)
            if len(self.buffer[channel]) > 131072:
                raise ValueError("native output line ceiling exhausted")
            while b"\n" in self.buffer[channel]:
                line, _, tail = self.buffer[channel].partition(b"\n")
                self.buffer[channel][:] = tail
                text = line.decode("utf8")
                if channel == "stdout":
                    self.journal.emit("recv", self.index, ns=stamp, text=text)
                    self.ready.append((text, stamp))
                    if len(self.ready) > 4096:
                        raise ValueError("native response queue exhausted")
                else:
                    self.runtime_seen |= str(self.scope["instrumented_runtime"]) in text
                    optional = line.startswith(b"dyld[")
                    if not optional:
                        self.critical.extend(line + b"\n")
                        if len(self.critical) > 65536:
                            raise ValueError("critical native diagnostic ceiling exhausted")
                    if optional and self.retained_stderr + len(line) + 1 > 262144:
                        self.dropped_stderr += len(line) + 1
                    else:
                        self.journal.emit("stderr", self.index, ns=stamp, text=text)
                        self.retained_stderr += len(line) + 1

    def until(self, predicate, seconds=10):
        deadline = min(time.time() + seconds, self.scope["deadline_unix"])
        collected = []
        while True:
            while self.ready:
                row = self.ready.pop(0)
                collected.append(row)
                if predicate(row[0]):
                    return collected
            if time.time() >= deadline or self.process.poll() is not None:
                raise ValueError("native response deadline or exit failure")
            self.pump()

    def setup(self, options):
        self.send("uci")
        self.until(lambda s: s == "uciok")
        for key, value in {**options, "Threads": self.threads, "EvalFile": self.scope["network"]}.items():
            value = str(value).lower() if type(value) is bool else str(value)
            self.send("setoption name " + key + " value " + value)
        self.send("isready")
        self.until(lambda s: s == "readyok")

    def close(self, success):
        if self.closed:
            return
        self.closed = True
        forced = False
        try:
            if success:
                self.send("quit")
            self.process.stdin.close()
            deadline = time.monotonic() + (3 if success else 0)
            while self.process.poll() is None and time.monotonic() < deadline:
                self.pump()
            if self.process.poll() is None:
                forced = True
                self.process.terminate()
                try:
                    self.process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    self.process.kill()
                    self.process.wait(timeout=2)
            while self.streams:
                self.pump()
            self.journal.emit("close", self.index, native_exit=self.process.returncode, forced_cleanup=forced, stderr_sha256=self.stderr_hash.hexdigest(), stderr_bytes=self.stderr_bytes, retained_stderr_bytes=self.retained_stderr, dropped_optional_bytes=self.dropped_stderr, critical_stderr_bytes=len(self.critical), runtime_seen=self.runtime_seen)
            if success and (forced or self.process.returncode != 0 or self.critical or (self.kind == "instrumented" and not self.runtime_seen)):
                raise ValueError("native exit, critical sanitizer diagnostic or runtime witness failed")
        finally:
            self.process.stdout.close()
            self.process.stderr.close()


def active(text):
    depth, nodes = re.search(r"\bdepth (\d+)\b", text), re.search(r"\bnodes (\d+)\b", text)
    return text.startswith("info ") and depth and nodes and int(depth[1]) >= 2 and int(nodes[1]) > 0


def produce(scope, quota):
    output = Path(scope["output"])
    (output / "producer").mkdir()
    profile = json.loads(Path(scope["profile"]).read_text())
    journal = Journal(output / "producer/transcript.jsonl", quota)
    completed, searches, sessions = 0, 0, 0
    failure = None
    try:
        for kind in ["release", "instrumented"]:
            for threads in profile["thread_modes"]:
                client = Native(scope, journal, sessions, kind, threads)
                sessions += 1
                success = False
                try:
                    client.setup(profile["options"])
                    count = 1000 if kind == "release" else 16
                    for index in range(count):
                        position = profile["positions"][index % 4]
                        client.send("ucinewgame")
                        client.send("position fen " + position["fen"])
                        client.send("isready")
                        client.until(lambda s: s == "readyok")
                        client.send("go infinite" if kind == "release" else "go nodes 2048")
                        if kind == "release":
                            client.until(active)
                            if any(line.startswith("bestmove ") for line, _ in client.ready):
                                raise ValueError("search completed before the required active stop")
                            client.send("stop")
                        client.until(lambda s: s.startswith("bestmove "))
                        if kind == "release":
                            completed += 1
                        else:
                            searches += 1
                        if index % 50 == 0:
                            journal.stream.flush()
                            atomic(output / "producer/PROGRESS.json", {"phase": kind, "threads": threads, "stop_sequences": completed, "instrumented_searches": searches})
                    success = True
                finally:
                    client.close(success)
        if completed != 4000 or searches != 64:
            raise ValueError("fixed thread workload incomplete")
    except BaseException as error:
        failure = str(error)
        raise
    finally:
        journal.close()
        atomic(output / "producer/SUMMARY.json", {"status": "observed" if failure is None else "failed", "stop_sequences": completed, "instrumented_searches": searches, "sessions": sessions, "frames": journal.frames, "transcript_sha256": journal.hash.hexdigest(), "failure": failure, "full_acceptance": False})
