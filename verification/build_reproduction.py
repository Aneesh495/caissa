"""Independently join committed source, dependency bytes, objects, archives and images."""

import hashlib
import json
import re
import shlex
import subprocess
import time
from pathlib import Path

from verification.source import NATIVE, PRODUCT, relative_path, require, snapshot


def digest(data):
    return hashlib.sha256(data).hexdigest()


def make_inputs(raw, directory):
    text = raw.decode().replace("\\\n", "")
    require(text.startswith("caissa-input:"), "compiler dependency target differs")
    words = re.findall(r"(?:\\.|[^\s])+", text[len("caissa-input:") :])
    return sorted(
        {
            str((Path(directory) / re.sub(r"\\(.)", r"\1", word)).resolve())
            for word in words
        }
    )


def compile_graph_arguments(arguments, directory):
    """Ninja adds dependency-file switches outside compile_commands.json."""
    result, index = [], 0
    while index < len(arguments):
        word = arguments[index]
        if word in {"-MF", "-MT", "-MQ"}:
            index += 2
        elif word in {"-MD", "-MMD", "-MP"}:
            index += 1
        elif word in {"-o", "-c"}:
            result.extend(
                [word, str((Path(directory) / arguments[index + 1]).resolve())]
            )
            index += 2
        else:
            result.append(word)
            index += 1
    return result


def archive_members(raw):
    require(raw.startswith(b"!<arch>\n"), "runtime core archive format differs")
    offset, names, result = 8, b"", {}
    while offset < len(raw):
        header = raw[offset : offset + 60]
        require(
            len(header) == 60 and header[-2:] == b"`\n",
            "runtime archive header differs",
        )
        size = int(header[48:58].strip())
        data = raw[offset + 60 : offset + 60 + size]
        require(len(data) == size, "runtime archive member is truncated")
        name = header[:16].strip().decode()
        if name == "//":
            names = data
        elif name.startswith("#1/"):
            count = int(name[3:])
            name = data[:count].rstrip(b"\0").decode()
            data = data[count:]
        elif name.startswith("/") and name[1:].isdigit():
            name = names[int(name[1:]) :].split(b"/\n", 1)[0].decode()
        else:
            name = name.rstrip("/")
        if name.endswith(".o"):
            require(name not in result, "runtime archive repeats an object")
            result[name] = digest(data)
        offset += 60 + size + size % 2
    require(offset == len(raw), "runtime archive has trailing bytes")
    return result


def verify(
    root,
    checkout,
    commit,
    profile_sha,
    *,
    replay_dependencies=False,
    deadline=None,
    replay_output=None,
):
    root, checkout = Path(root), Path(checkout)
    if replay_dependencies:
        require(
            replay_output is not None, "independent compiler replay output required"
        )
        replay_output = Path(replay_output)
        replay_output.mkdir(parents=True, exist_ok=False)
    profile_raw = (root / "PROFILE.json").read_bytes()
    require(digest(profile_raw) == profile_sha, "external build profile differs")
    profile = json.loads(profile_raw)
    require(
        profile["builds"] == 2 and len(profile["runtime_units"]) == 21,
        "runtime unit profile differs",
    )
    require(
        profile["full_G15_certified"] is False, "build component promoted to full gate"
    )
    source = json.loads((root / "SOURCE_INPUTS.json").read_text())
    require(
        source["commit"] == commit
        and source["files"] == snapshot(checkout, commit, PRODUCT),
        "committed build source differs",
    )
    require(
        source["native"]
        == snapshot(checkout, commit, NATIVE)
        == snapshot(checkout, profile["compiled_original_source"], NATIVE),
        "original native source join differs",
    )
    manifest = json.loads((root / "MANIFEST.json").read_text())["files"]
    require(len(manifest) <= 50000, "build manifest file ceiling exhausted")
    for name, value in manifest.items():
        path = root / relative_path(name)
        require(
            path.is_file()
            and not path.is_symlink()
            and digest(path.read_bytes()) == value,
            "build manifest bytes differ",
        )
    compiled, scanned, dependencies, images = 0, 0, set(), []
    compiler = json.loads((root / "toolchain/COMPILER.json").read_text())
    compiler_data = (root / "toolchain/blobs" / compiler["sha256"]).read_bytes()
    require(
        digest(compiler_data) == compiler["sha256"]
        and len(compiler_data) == compiler["bytes"],
        "retained compiler bytes differ",
    )
    for label in ["build-1", "build-2"]:
        folder, cache = root / label, {}
        trace = folder / "trace"

        def blob(row):
            value = row["sha256"]
            require(
                isinstance(value, str) and re.fullmatch("[a-f0-9]{64}", value),
                "compiler blob identity differs",
            )
            if value not in cache:
                raw = (trace / "blobs" / value).read_bytes()
                require(digest(raw) == value, "compiler blob bytes differ")
                cache[value] = raw
            require(
                len(cache[value]) == row["bytes"] and row["bytes"] > 0,
                "compiler blob length differs",
            )
            return cache[value]

        records = [
            json.loads(p.read_text())
            for p in trace.glob("*.json")
            if p.name != "link.json"
        ]
        by_source = {record["source"]: record for record in records}
        require(
            len(records) == len(by_source) == len(profile["runtime_units"])
            and set(by_source) == set(profile["runtime_units"]),
            "actual compiled unit inventory differs",
        )
        commands = json.loads((folder / "compile_commands.json").read_text())
        database = {row["file"]: row for row in commands}
        configured = (folder / "CMakeCache.txt").read_text()
        require(
            all(
                value in configured.splitlines()
                for value in [
                    "CMAKE_BUILD_TYPE:STRING=Release",
                    "CAISSA_NETWORK_WIDTH:STRING=64",
                    "CAISSA_SANITIZE:BOOL=OFF",
                    "CAISSA_TSAN:BOOL=OFF",
                ]
            ),
            "configured native build policy differs",
        )
        objects = {}
        for name in profile["runtime_units"]:
            require(
                deadline is None or time.time() < deadline,
                "independent build deadline exhausted",
            )
            record = by_source[name]
            require(
                record["mode"] == "compile"
                and record["exit"] == 0
                and record["end_unix"] >= record["start_unix"],
                "actual compiler invocation failed",
            )
            require(
                record["compiler"]
                == {"path": compiler["path"], "sha256": compiler["sha256"]},
                "compiler identity differs",
            )
            require(
                record["inputs_before"] == record["inputs_after"],
                "consumed compiler input changed",
            )
            native_source = str(Path(record["checkout"]) / name)
            command = database[native_source]
            require(
                compile_graph_arguments(
                    shlex.split(command["command"]), command["directory"]
                )
                == compile_graph_arguments(record["argv"], record["directory"])
                and command["directory"] == record["directory"],
                "actual compiler command differs from build graph",
            )
            require(
                all(
                    flag in record["argv"]
                    for flag in [
                        "-DCAISSA_NETWORK_WIDTH=64",
                        "-O3",
                        "-DNDEBUG",
                        "-std=c++23",
                    ]
                ),
                "compiled runtime flags differ",
            )
            raw_deps = (trace / (name.replace("/", "_") + ".deps")).read_bytes()
            observed_inputs = make_inputs(raw_deps, record["directory"])
            require(
                observed_inputs
                == sorted(row["path"] for row in record["inputs_before"]),
                "consumed dependency inventory differs",
            )
            require(
                native_source in observed_inputs,
                "compiler did not consume its declared source",
            )
            for row in record["inputs_before"]:
                data = blob(row)
                path = Path(row["path"])
                if path.is_relative_to(record["checkout"]):
                    relative = str(path.relative_to(record["checkout"]))
                    require(
                        relative in source["files"]
                        and digest(data) == source["files"][relative],
                        "consumed project source differs from committed Git bytes",
                    )
                dependencies.add(row["sha256"])
            if replay_dependencies:
                require(
                    digest(Path(compiler["path"]).read_bytes()) == compiler["sha256"],
                    "live replay compiler differs",
                )
                original, filtered, index = record["argv"], [], 0
                while index < len(original):
                    word = original[index]
                    if word in {"-o", "-MF", "-MT", "-MQ"}:
                        index += 2
                    elif word in {"-c", "-MD", "-MMD", "-MP"}:
                        index += 1
                    else:
                        filtered.append(word)
                        index += 1
                timeout = 120 if deadline is None else min(120, deadline - time.time())
                require(timeout > 0, "independent compiler deadline exhausted")
                replay_started = time.time()
                replay_command = filtered + ["-M", "-MT", "caissa-input", "-MF", "-"]
                actual = subprocess.run(
                    replay_command,
                    cwd=record["directory"],
                    capture_output=True,
                    timeout=timeout,
                )
                scan_name = label + "-" + name.replace("/", "_")
                (replay_output / (scan_name + ".deps")).write_bytes(
                    actual.stdout[: 4 * 1024**2]
                )
                (replay_output / (scan_name + ".stderr")).write_bytes(
                    actual.stderr[: 4 * 1024**2]
                )
                with (replay_output / "SCANS.jsonl").open("a") as stream:
                    stream.write(
                        json.dumps(
                            {
                                "source": name,
                                "build": label,
                                "argv": replay_command,
                                "directory": record["directory"],
                                "exit": actual.returncode,
                                "stdout_sha256": digest(actual.stdout),
                                "stderr_sha256": digest(actual.stderr),
                                "start_unix": replay_started,
                                "end_unix": time.time(),
                            }
                        )
                        + "\n"
                    )
                require(
                    actual.returncode == 0 and len(actual.stdout) <= 4 * 1024**2,
                    "independent compiler dependency scan failed",
                )
                require(
                    make_inputs(actual.stdout, record["directory"]) == observed_inputs,
                    "independent compiler dependency closure differs",
                )
                scanned += 1
            blob(record["output"])
            objects[name] = record["output"]["sha256"]
            compiled += 1
        link = json.loads((trace / "link.json").read_text())
        require(
            link["mode"] == "link"
            and link["exit"] == 0
            and link["inputs_before"] == link["inputs_after"],
            "actual link driver failed or inputs changed",
        )
        require(
            link["compiler"]
            == {"path": compiler["path"], "sha256": compiler["sha256"]},
            "link driver identity differs",
        )
        require(len(link["inputs_before"]) == 2, "runtime link input inventory differs")
        archive = next(
            row for row in link["inputs_before"] if row["path"].endswith(".a")
        )
        main = next(row for row in link["inputs_before"] if row["path"].endswith(".o"))
        require(
            main["sha256"] == objects["apps/main.cpp"],
            "linked application object differs",
        )
        blob(main)
        require(
            archive_members(blob(archive))
            == {
                Path(name).name + ".o": value
                for name, value in objects.items()
                if name != "apps/main.cpp"
            },
            "linked archive object membership differs",
        )
        binary = (folder / "caissa").read_bytes()
        require(blob(link["output"]) == binary, "linked executable bytes differ")
        images.append(digest(binary))
    require(images[0] == images[1], "independent two-build executable bytes differ")
    return {
        "component_pass": True,
        "compiled_units": compiled,
        "independent_dependency_scans": scanned,
        "distinct_consumed_blobs": len(dependencies),
        "binary_sha256": images[0],
        "source_commit": commit,
        "saved_original_compiler_invocation_proven": False,
        "runtime_dynamic_dependency_closure_proven": False,
        "full_G15_certified": False,
        "full_acceptance": False,
    }
