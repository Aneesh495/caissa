"""Observe actual CMake compiler and link-driver invocations and consumed bytes."""

import argparse
import hashlib
import json
import os
import shlex
import subprocess
import time
from pathlib import Path


def sha(path):
    result = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024**2), b""):
            result.update(block)
    return result.hexdigest()


def retain(path, output, limit=8 * 1024**2):
    path = Path(path).resolve(strict=True)
    if not path.is_file() or not 0 < path.stat().st_size <= limit:
        raise ValueError("compiler input is absent or exceeds its byte ceiling")
    data = path.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    destination = output / "blobs" / digest
    destination.parent.mkdir(parents=True, exist_ok=True)
    if not destination.exists():
        temporary = destination.with_suffix("." + str(os.getpid()))
        with temporary.open("xb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(temporary, destination)
        except FileExistsError:
            if sha(destination) != digest:
                raise ValueError("compiler input blob changed")
        finally:
            temporary.unlink()
    return {"path": str(path), "sha256": digest, "bytes": len(data)}


def dependency_command(command):
    result, index = [], 0
    while index < len(command):
        word = command[index]
        if word in {"-o", "-MF", "-MT", "-MQ"}:
            index += 2
        elif word in {"-c", "-MD", "-MMD", "-MP"}:
            index += 1
        else:
            result.append(word)
            index += 1
    return result + ["-M", "-MT", "caissa-input", "-MF", "-"]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--mode", choices=["compile", "link"], default="compile")
    parser.add_argument("arguments", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = args.arguments[1:] if args.arguments[:1] == ["--"] else args.arguments
    if not command or "-o" not in command:
        raise ValueError("actual compiler output argument required")
    if args.mode == "link" and Path(command[command.index("-o") + 1]).name != "caissa":
        # CMake must retain its ordinary compiler and IPO capability probes.
        return subprocess.call(command)
    checkout, output = args.source.resolve(), args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    compiler = Path(command[0]).resolve(strict=True)
    compiler_before = sha(compiler)
    source = None
    if args.mode == "compile":
        if "-c" not in command:
            raise ValueError("actual compilation argument required")
        source = Path(command[command.index("-c") + 1]).resolve(strict=True)
        if not source.is_relative_to(checkout) or source.parts[-2] not in {
            "src",
            "apps",
        }:
            return subprocess.call(command)
        # Keep the compiler's module source name independent of the fresh clone's
        # absolute directory while recording the exact command actually executed.
        command[command.index("-c") + 1] = os.path.relpath(source, Path.cwd())
        name = str(source.relative_to(checkout)).replace("/", "_")
        observed = subprocess.run(
            dependency_command(command), capture_output=True, timeout=120
        )
        (output / (name + ".deps")).write_bytes(observed.stdout[: 4 * 1024**2])
        (output / (name + ".deps.stderr")).write_bytes(observed.stderr[: 4 * 1024**2])
        if observed.returncode:
            raise ValueError(
                "actual compiler dependency query failed: "
                + observed.stderr.decode(errors="replace")[-2048:]
            )
        if len(observed.stdout) > 4 * 1024**2:
            raise ValueError("compiler dependency output ceiling exhausted")
        text = observed.stdout.decode().replace("\\\n", "")
        if not text.startswith("caissa-input:"):
            raise ValueError("compiler dependency target differs")
        inputs = sorted(
            {
                str(Path(path).resolve(strict=True))
                for path in shlex.split(text[len("caissa-input:") :])
            }
        )
        if not 0 < len(inputs) <= 4096:
            raise ValueError("compiler dependency inventory outside ceiling")
    else:
        inputs = [
            word
            for word in command[1:]
            if word.endswith((".o", ".a")) and Path(word).is_file()
        ]
        if len(inputs) != 2:
            raise ValueError(
                "declared runtime link requires one application object and one core archive"
            )
        name = "link"
    before = [
        retain(path, output, 256 * 1024**2 if args.mode == "link" else 8 * 1024**2)
        for path in inputs
    ]
    if (
        sum(row["bytes"] for row in before)
        > (512 if args.mode == "link" else 64) * 1024**2
    ):
        raise ValueError("compiler invocation input byte ceiling exhausted")
    started = time.time()
    actual = subprocess.run(command, timeout=120)
    after = [
        {**row, "sha256": sha(row["path"]), "bytes": Path(row["path"]).stat().st_size}
        for row in before
    ]
    target = Path(command[command.index("-o") + 1]).resolve()
    result = {
        "schema": "caissa-actual-compiler-invocation-v1",
        "mode": args.mode,
        "source": str(source.relative_to(checkout)) if source else None,
        "checkout": str(checkout),
        "directory": str(Path.cwd().resolve()),
        "argv": command,
        "compiler": {"path": str(compiler), "sha256": compiler_before},
        "inputs_before": before,
        "inputs_after": after,
        "output": (
            retain(target, output, 256 * 1024**2) if actual.returncode == 0 else None
        ),
        "exit": actual.returncode,
        "start_unix": started,
        "end_unix": time.time(),
    }
    with (output / (name + ".json")).open("x") as stream:
        json.dump(result, stream, separators=(",", ":"))
        stream.write("\n")
    if actual.returncode:
        return actual.returncode
    if before != after or sha(compiler) != compiler_before:
        raise ValueError("compiler or consumed input changed during actual invocation")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
