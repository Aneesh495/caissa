"""A bounded UCI process owner. The arena, not this client, judges chess legality."""

import queue, subprocess, threading, time


class EngineFailure(RuntimeError):
    pass


def parse_options(lines):
    options = {}
    for line in lines:
        if not line.startswith("option name "):
            continue
        fields = line.split()
        try:
            marker = fields.index("type", 2)
        except ValueError:
            raise EngineFailure("malformed engine option declaration")
        name = " ".join(fields[2:marker])
        kind = fields[marker + 1] if marker + 1 < len(fields) else ""
        if (
            not name
            or kind not in ["check", "spin", "combo", "button", "string"]
            or name in options
        ):
            raise EngineFailure("invalid or duplicate engine option declaration")
        option = {"type": kind}
        position = marker + 2
        while position < len(fields):
            key = fields[position]
            position += 1
            if key not in ["default", "min", "max", "var"]:
                raise EngineFailure("malformed option metadata")
            end = position
            while end < len(fields) and fields[end] not in [
                "default",
                "min",
                "max",
                "var",
            ]:
                end += 1
            value = " ".join(fields[position:end])
            position = end
            if key == "var":
                option.setdefault("choices", []).append(value)
            else:
                option[key] = value
        options[name] = option
    return options


def validate_option(name, value, available):
    if name not in available:
        raise EngineFailure("requested engine option is undeclared: " + str(name))
    contract = available[name]
    kind = contract["type"]
    if kind == "spin":
        if not isinstance(value, int) or isinstance(value, bool):
            raise EngineFailure("integer engine option required: " + name)
        try:
            low = int(contract["min"])
            high = int(contract["max"])
        except (KeyError, ValueError):
            raise EngineFailure("engine spin bounds are malformed: " + name)
        if not low <= value <= high:
            raise EngineFailure("engine option outside declared bounds: " + name)
    elif kind == "check" and not isinstance(value, bool):
        raise EngineFailure("boolean engine option required: " + name)
    elif kind == "combo" and str(value) not in contract.get("choices", []):
        raise EngineFailure("engine option choice undeclared: " + name)
    elif kind == "string" and not isinstance(value, str):
        raise EngineFailure("string engine option required: " + name)


class UciClient:
    def __init__(self, command, options, timeout=10, warmup_nodes=0):
        try:
            self.process = subprocess.Popen(
                command,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                bufsize=1,
            )
        except OSError as e:
            raise EngineFailure("engine startup failed: " + str(e)) from e
        self.lines = queue.Queue(maxsize=10000)
        self.timeout = timeout

        def reader():
            try:
                while True:
                    line = self.process.stdout.readline(16385)
                    if not line or len(line) > 16384:
                        break
                    try:
                        self.lines.put(line.strip(), timeout=1)
                    except queue.Full:
                        break
            finally:
                try:
                    self.lines.put(None, timeout=0.1)
                except queue.Full:
                    pass

        self.reader = threading.Thread(target=reader, daemon=True)
        self.reader.start()
        try:
            self.send("uci")
            self.handshake = self.until("uciok", timeout)
            self.available_options = parse_options(self.handshake)
            self.configuration_commands = []
            for name, value in options.items():
                if any(c in str(name) + str(value) for c in "\r\n\0"):
                    raise ValueError("invalid option delimiter")
                validate_option(name, value, self.available_options)
                command = (
                    f"setoption name {name}"
                    if self.available_options[name]["type"] == "button"
                    else f"setoption name {name} value {str(value).lower() if isinstance(value,bool) else value}"
                )
                self.send(command)
                self.configuration_commands.append(command)
            self.send("isready")
            self.until("readyok", timeout)
            self.warmup_ms = 0.0
            if warmup_nodes:
                start = time.monotonic_ns()
                self.send("position startpos")
                self.send(f"go nodes {warmup_nodes}")
                self.until("bestmove ", timeout)
                self.warmup_ms = (time.monotonic_ns() - start) / 1e6
                self.send("ucinewgame")
                self.send("isready")
                self.until("readyok", timeout)
        except BaseException:
            self.close()
            raise

    def send(self, line):
        if len(line) > 8192:
            raise EngineFailure("command too long")
        try:
            self.process.stdin.write(line + "\n")
            self.process.stdin.flush()
        except (BrokenPipeError, OSError) as e:
            raise EngineFailure("engine pipe closed") from e

    def until(self, prefix, timeout):
        deadline = time.monotonic() + timeout
        lines = []
        while True:
            try:
                line = self.lines.get(timeout=max(0.001, deadline - time.monotonic()))
            except queue.Empty as e:
                raise EngineFailure("engine response timeout") from e
            if line is None:
                raise EngineFailure("engine exited")
            lines.append(line)
            if line.startswith("info string error "):
                raise EngineFailure("engine rejected command: " + line[18:])
            if len(lines) > 5000:
                raise EngineFailure("engine output flood")
            if line.startswith(prefix):
                return lines
            if time.monotonic() > deadline:
                raise EngineFailure("engine response timeout")

    def play(self, initial, moves, nodes=None, milliseconds=None):
        position_command = (
            "position fen " + initial + (" moves " + " ".join(moves) if moves else "")
        )
        self.send(position_command)
        command = (
            f"go nodes {nodes}" if nodes is not None else f"go movetime {milliseconds}"
        )
        start = time.monotonic_ns()
        self.send(command)
        lines = self.until("bestmove ", max(2.0, (milliseconds or 0) / 1000 + 1))
        finished = time.monotonic_ns()
        elapsed = (finished - start) / 1e6
        self.last_request = {
            "position": position_command,
            "go": command,
            "started_monotonic_ns": start,
            "completed_monotonic_ns": finished,
        }
        return lines[-1].split()[1], elapsed, lines

    def close(self):
        p = self.process
        if p.poll() is None:
            try:
                self.send("stop")
                self.send("quit")
                p.wait(timeout=0.5)
            except (EngineFailure, subprocess.TimeoutExpired):
                p.kill()
                p.wait(timeout=2)
        for stream in [p.stdin, p.stdout]:
            if stream:
                stream.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()
