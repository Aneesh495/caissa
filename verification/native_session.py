"""Independent bounded native transport for saved-engine verification.

No arena client, producer parser or search implementation is imported. Each
session owns its executable process group, finite input/output and teardown.
"""

import os
import math
import selectors
import signal
import subprocess
import time
from pathlib import Path


class NativeSession:
    def __init__(
        self,
        engine,
        options,
        deadline,
        *,
        maximum_bytes=64 * 1024 * 1024,
        new_session=True,
    ):
        if (
            not math.isfinite(deadline)
            or type(maximum_bytes) is not int
            or not 1024 <= maximum_bytes <= 64 * 1024 * 1024
            or type(new_session) is not bool
        ):
            raise ValueError("finite native deadline and output byte bound required")
        self.deadline = deadline
        self.new_session = new_session
        self.maximum_bytes = maximum_bytes
        self.received_bytes = 0
        self.buffer = b""
        self.events = []
        self.stderr = bytearray()
        self.process = subprocess.Popen(
            [str(Path(engine).resolve())],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=new_session,
        )
        self.reader = selectors.DefaultSelector()
        self.writer = selectors.DefaultSelector()
        os.set_blocking(self.process.stdout.fileno(), False)
        os.set_blocking(self.process.stdin.fileno(), False)
        os.set_blocking(self.process.stderr.fileno(), False)
        self.reader.register(self.process.stdout, selectors.EVENT_READ, "stdout")
        self.reader.register(self.process.stderr, selectors.EVENT_READ, "stderr")
        self.writer.register(self.process.stdin, selectors.EVENT_WRITE)
        try:
            self.send("uci")
            self.handshake = self.until("uciok")
            declarations = {}
            for line in self.handshake:
                if line.startswith("option name ") and " type " in line:
                    name, description = line[12:].split(" type ", 1)
                    declarations[name] = description
            for name, value in options.items():
                if name not in declarations:
                    raise ValueError(
                        "independent native replay requested undeclared option: " + name
                    )
                text = str(value).lower() if type(value) is bool else str(value)
                if any(c in name + text for c in "\r\n\0"):
                    raise ValueError("invalid native option delimiter")
                self.send("setoption name " + name + " value " + text)
            self.send("isready")
            self.until("readyok")
            self.send("position startpos")
            self.send("go nodes 1")
            self.until("bestmove ")
            self.send("ucinewgame")
            self.ready()
        except BaseException:
            self.close()
            raise

    def _timeout(self, seconds):
        remaining = min(seconds, self.deadline - time.time())
        if remaining <= 0:
            raise TimeoutError("independent native replay deadline exhausted")
        return remaining

    def send(self, line):
        if (
            not isinstance(line, str)
            or len(line.encode()) > 8192
            or any(c in line for c in "\r\n\0")
        ):
            raise ValueError("independent native command outside finite contract")
        payload = (line + "\n").encode()
        until = time.monotonic() + self._timeout(3)
        if len(self.events) >= 100000:
            raise ValueError("independent native event count ceiling")
        self.events.append(
            {"direction": "send", "line": line, "monotonic_ns": time.monotonic_ns()}
        )
        while payload:
            remaining = min(until - time.monotonic(), self._timeout(3))
            if remaining <= 0 or not self.writer.select(remaining):
                raise TimeoutError("independent native write deadline")
            try:
                count = os.write(self.process.stdin.fileno(), payload)
            except BlockingIOError:
                continue
            if count <= 0:
                raise ValueError("independent native stdin closed")
            payload = payload[count:]

    def line(self, seconds=3):
        until = time.monotonic() + self._timeout(seconds)
        while b"\n" not in self.buffer:
            if len(self.buffer) > 16384:
                raise ValueError("independent native response line ceiling")
            remaining = min(until - time.monotonic(), self._timeout(seconds))
            if remaining <= 0:
                raise TimeoutError("independent native response deadline")
            ready = self.reader.select(remaining)
            if not ready:
                raise TimeoutError("independent native response deadline")
            for key, _ in ready:
                block = os.read(key.fd, 65536)
                if key.data == "stderr":
                    if not block:
                        self.reader.unregister(key.fileobj)
                        continue
                    if len(self.stderr) + len(block) > 1024 * 1024:
                        raise ValueError("independent native stderr byte ceiling")
                    self.stderr.extend(block)
                    continue
                if not block:
                    raise ValueError("independent native stdout closed")
                self.received_bytes += len(block)
                if self.received_bytes > self.maximum_bytes:
                    raise ValueError("independent native output byte ceiling")
                self.buffer += block
        raw, self.buffer = self.buffer.split(b"\n", 1)
        if len(raw) > 16384:
            raise ValueError("independent native response line ceiling")
        line = raw.decode("utf-8").rstrip("\r")
        if len(self.events) >= 100000:
            raise ValueError("independent native event count ceiling")
        self.events.append(
            {"direction": "receive", "line": line, "monotonic_ns": time.monotonic_ns()}
        )
        return line

    def until(self, prefix, seconds=3):
        rows = []
        until = time.monotonic() + self._timeout(seconds)
        while len(rows) < 5000:
            line = self.line(min(seconds, max(0.001, until - time.monotonic())))
            if time.monotonic() > until:
                raise TimeoutError("independent native phase deadline")
            rows.append(line)
            if line.startswith("info string error "):
                raise ValueError("saved native executable rejected replay: " + line)
            if line.startswith(prefix):
                return rows
        raise ValueError("independent native phase line ceiling")

    def ready(self):
        self.send("isready")
        self.until("readyok")

    def search(self, fen, nodes):
        self.send("ucinewgame")
        self.ready()
        self.send("position fen " + fen)
        self.send("go nodes " + str(nodes))
        return self.until("bestmove ")

    def close(self):
        if getattr(self, "closed", False):
            return
        self.closed = True
        process = getattr(self, "process", None)
        if process is not None:
            if process.poll() is None:
                try:
                    os.write(process.stdin.fileno(), b"stop\nquit\n")
                except (BrokenPipeError, BlockingIOError, OSError):
                    pass
                try:
                    process.wait(timeout=0.25)
                except subprocess.TimeoutExpired:
                    try:
                        if self.new_session:
                            os.killpg(process.pid, signal.SIGTERM)
                        else:
                            process.terminate()
                    except ProcessLookupError:
                        pass
                    try:
                        process.wait(timeout=2)
                    except subprocess.TimeoutExpired:
                        try:
                            if self.new_session:
                                os.killpg(process.pid, signal.SIGKILL)
                            else:
                                process.kill()
                        except ProcessLookupError:
                            pass
                        process.wait(timeout=3)
            # Terminate any same-group descendant left by an adversarial peer.
            if self.new_session:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            for pipe in [process.stdin, process.stdout, process.stderr]:
                if pipe is not None:
                    pipe.close()
        for name in ["reader", "writer"]:
            value = getattr(self, name, None)
            if value is not None:
                value.close()

    def __enter__(self):
        return self

    def __exit__(self, *unused):
        self.close()
