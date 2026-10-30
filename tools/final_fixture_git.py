"""Unexecuted bounded transport for the fixture owner's exact source Git reads."""

import hashlib
import os
from pathlib import Path
import re
import resource
import selectors
import subprocess
import time


class FixtureGit:
    def __init__(self, root, scope, guard):
        self.root, self.scope, self.guard = Path(root), scope, guard
        self.original_run, self.original_popen = subprocess.run, subprocess.Popen
        self.rows, self.pending, self.active = [], None, None
        self.order = (["git", "rev-parse", "HEAD"],
                      ["git", "ls-tree", "-r", "-l", "-z", "--full-tree", scope["product_commit"]],
                      ["git", "cat-file", "--batch"])

    def require(self, value, reason):
        if not value:
            raise ValueError(reason)

    def install(self):
        self.require(subprocess.run is self.original_run, "fixture Git transport already changed")
        subprocess.run = self.run

    def uninstall(self):
        subprocess.run = self.original_run

    def admit_spawn(self, args):
        command = self.pending
        self.require(command is not None and args[0] == self.scope["git_executable"]
                     and args[1] == command and Path(args[2]).resolve() == self.root,
                     "fixture owner rejects unowned or unexpected child command")
        self.pending = None

    def run(self, command, **kwargs):
        self.guard()
        index = len(self.rows)
        self.require(index < self.scope["maximum_source_git_commands"]
                     and command == self.order[index % 3] and self.active is None,
                     "fixture Git order or command count differs")
        allowed = {"cwd", "input", "capture_output", "timeout", "check", "text", "stdout"}
        self.require(set(kwargs) <= allowed and Path(kwargs["cwd"]).resolve() == self.root
                     and kwargs.get("check") is True
                     and (kwargs.get("capture_output") is True or kwargs.get("stdout") == subprocess.PIPE),
                     "fixture Git call options differ from the pinned source reader")
        query = kwargs.get("input", b"")
        self.require(type(query) is bytes and len(query) <= 410000
                     and (index % 3 == 2 and query and re.fullmatch(b"(?:[0-9a-f]{40}\n)+", query)
                          or index % 3 != 2 and not query), "fixture Git input is not a bounded object query")
        seconds = kwargs["timeout"]
        self.require(type(seconds) in {int, float} and 0 < seconds <= (5, 10, 15)[index % 3]
                     and bool(kwargs.get("text", False)) is (index % 3 == 0),
                     "fixture Git time or text mode differs")
        deadline = min(time.monotonic() + seconds,
                       time.monotonic() + self.scope["deadline_unix"] - time.time() - 10)
        self.require(deadline > time.monotonic(), "fixture Git cleanup window exhausted")
        maximum = (128, 2 * 1024**2, 32 * 1024**2 + 10000 * 128)[index % 3]
        environment = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
        environment.pop("CAISSA_HOST_LEASE_FD", None)
        environment.update(GIT_OPTIONAL_LOCKS="0", GIT_CONFIG_NOSYSTEM="1",
                           GIT_CONFIG_SYSTEM=os.devnull, GIT_CONFIG_GLOBAL=os.devnull,
                           GIT_CONFIG_COUNT="0", GIT_TERMINAL_PROMPT="0")
        actual = [self.scope["git_executable"], *command[1:]]
        reaped = resource.getrusage(resource.RUSAGE_CHILDREN)
        unused_child_cpu = (self.scope["maximum_family_cpu_seconds"]
                            - self.scope["maximum_owner_cpu_seconds"] - reaped.ru_utime - reaped.ru_stime)
        inherited = resource.getrlimit(resource.RLIMIT_CPU)[1]
        child_cpu = int(unused_child_cpu)
        if inherited != resource.RLIM_INFINITY:
            child_cpu = min(child_cpu, inherited)
        self.require(child_cpu > 0, "fixture Git cumulative child CPU budget exhausted")

        def child_limits():
            resource.setrlimit(resource.RLIMIT_CPU, (child_cpu, child_cpu))
            resource.setrlimit(resource.RLIMIT_FSIZE, (0, 0))
            resource.setrlimit(resource.RLIMIT_CORE, (0, 0))

        selector, process, failure, cleanup = selectors.DefaultSelector(), None, None, []
        retained = {"stdout": bytearray(), "stderr": bytearray()}
        counts, hashes, eof = ({k: 0 for k in retained}, {k: hashlib.sha256() for k in retained},
                              {k: False for k in retained})
        row = {"ordinal": index + 1, "kind": ("head", "tree", "blobs")[index % 3],
               "input_bytes": len(query), "input_sha256": hashlib.sha256(query).hexdigest(),
               "child_cpu_hard_seconds": child_cpu, "child_regular_file_ceiling_bytes": 0}
        self.rows.append(row)  # A failed start consumes this command slot.
        try:
            self.pending = actual
            process = self.original_popen(actual, stdin=subprocess.PIPE if query else subprocess.DEVNULL,
                                          stdout=subprocess.PIPE, stderr=subprocess.PIPE, bufsize=0,
                                          cwd=self.root, env=environment, start_new_session=False,
                                          preexec_fn=child_limits)
            self.active = process
            self.require(self.pending is None and os.getpgid(process.pid) == os.getpgrp(),
                         "fixture Git did not inherit the externally owned owner group")
            row.update(pid=process.pid, owner_group_id=os.getpgrp(), inherited_owner_group=True)
            for label, stream in (("stdout", process.stdout), ("stderr", process.stderr)):
                os.set_blocking(stream.fileno(), False)
                selector.register(stream, selectors.EVENT_READ, label)
            sent = 0
            if query:
                os.set_blocking(process.stdin.fileno(), False)
                selector.register(process.stdin, selectors.EVENT_WRITE, "stdin")
            stopped, killed = None, False
            while selector.get_map():
                now = time.monotonic()
                if failure is None:
                    try:
                        self.guard()
                        self.require(now < deadline, "fixture Git fixed command deadline exhausted")
                    except BaseException as error:
                        failure = error
                if failure is not None and stopped is None:
                    stopped = now
                    if process.poll() is None:
                        process.terminate()
                if stopped is not None and now - stopped >= 0.5 and not killed:
                    if process.poll() is None:
                        process.kill()
                    killed = True
                if stopped is not None and now - stopped >= 2:
                    break
                for key, _ in selector.select(0.05):
                    stream, label = key.fileobj, key.data
                    if label == "stdin":
                        try:
                            sent += os.write(stream.fileno(), query[sent:sent + 65536])
                        except BlockingIOError:
                            continue
                        except BrokenPipeError as error:
                            failure = failure or error
                            sent = len(query)
                        if sent == len(query):
                            selector.unregister(stream)
                            stream.close()
                        continue
                    try:
                        block = os.read(stream.fileno(), 65536)
                    except BlockingIOError:
                        continue
                    if not block:
                        eof[label] = True
                        selector.unregister(stream)
                        stream.close()
                        continue
                    counts[label] += len(block)
                    hashes[label].update(block)
                    cap = maximum if label == "stdout" else 65536
                    retained[label].extend(block[:max(0, cap - len(retained[label]))])
                    if counts[label] > cap and failure is None:
                        failure = ValueError("fixture Git output exceeded its separately bounded pipe")
            if failure is None:
                self.require(sent == len(query), "fixture Git input pipe was incomplete")
                process.wait(timeout=max(0.001, deadline - time.monotonic()))
        except BaseException as error:
            failure = failure or error
        finally:
            self.pending = None
            if process is not None:
                try:
                    if process.poll() is None:
                        process.kill()
                    process.wait(timeout=2)
                except BaseException as error:
                    cleanup.append(type(error).__name__)
                for stream in (process.stdin, process.stdout, process.stderr):
                    if stream is not None and not stream.closed:
                        stream.close()
            selector.close()
            self.active = None
            row.update(exit=process.returncode if process is not None else None,
                       observed_bytes=counts, observed_sha256={k: h.hexdigest() for k, h in hashes.items()},
                       retained_bytes={k: len(v) for k, v in retained.items()}, eof=eof,
                       discarded_bytes={k: counts[k] - len(retained[k]) for k in retained},
                       cleanup_errors=cleanup)
        if cleanup:
            if failure is not None:
                failure.add_note("fixture Git cleanup also failed: " + ", ".join(cleanup))
            else:
                failure = RuntimeError("fixture Git actual child reaping failed")
        if failure is not None:
            raise failure
        self.require(row["exit"] == 0 and all(eof.values()) and counts["stderr"] == 0
                     and not any(row["discarded_bytes"].values()),
                     "fixture Git actual exit, clean streams or complete EOF differs")
        self.guard()
        output = bytes(retained["stdout"])
        return subprocess.CompletedProcess(command, 0,
                                           output.decode() if kwargs.get("text") else output,
                                           "" if kwargs.get("text") else b"")
