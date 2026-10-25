"""Full strength resource/actor controls, persistent ceilings and host isolation."""

import copy
import json
import os
import tempfile
from pathlib import Path

from tools.full_strength import configuration, offenders, process_rows, validate_matches
from tools.recovery_scope import RecoveryScope
from verification.external_strength import external_options


def main():
    rule = json.loads(Path("config/protocol-v3.proposed.json").read_text())
    validate_matches(rule)
    rejected = []
    for key, value in [
        ("milliseconds", 20),
        ("threads", 2),
        ("hash_mib", 8),
        ("workers", 3),
        ("warmup_nodes", 0),
        ("transport_allowance_ms", 200),
        ("maximum_plies", 1024),
        ("neural_pairs", 1999),
        ("external_pairs", [333, 333, 333]),
        ("maximum_neural_campaign_wall_seconds", 43201),
        ("maximum_external_campaign_wall_seconds", 43201),
    ]:
        changed = copy.deepcopy(rule)
        changed["matches"][key] = value
        try:
            validate_matches(changed)
        except ValueError:
            rejected.append(key)
        else:
            raise AssertionError("changed frozen strength setting admitted: " + key)
    engine, network, openings = map(
        Path, ["/frozen/caissa", "/frozen/selected.cai", "/frozen/openings.json"]
    )
    config = configuration(rule, engine, network, openings, None)
    left, right = config["candidate"], config["opponent"]
    removed = {"Use Neural", "EvalFile", "Neural Weight"}
    assert (
        left["command"] == right["command"] and right["options"]["Use Neural"] is False
    )
    assert {k: v for k, v in left["options"].items() if k not in removed} == {
        k: v for k, v in right["options"].items() if k not in removed
    }
    assert left["options"]["Neural Weight"] == 10 and config["pairs"] == 2000
    for i in range(3):
        external = configuration(
            rule, engine, network, openings, (i, Path("/frozen/stockfish"))
        )
        assert external["candidate"] == left
        assert external["opponent"]["options"] == external_options(i, rule["matches"])
        assert external["pairs"] == rule["matches"]["external_pairs"][i]
    rows = [
        {
            "pid": 100,
            "ppid": 1,
            "state": "S",
            "cpu": 0,
            "command": "python -m tools.full_strength neural",
        },
        {
            "pid": 101,
            "ppid": 100,
            "state": "S",
            "cpu": 0,
            "command": "python -m arena.run own/config own/output",
        },
        {
            "pid": 102,
            "ppid": 101,
            "state": "R",
            "cpu": 100,
            "command": "/frozen/caissa",
        },
        {
            "pid": 200,
            "ppid": 1,
            "state": "S",
            "cpu": 0,
            "command": "python -m verification.dataset data",
        },
        {
            "pid": 201,
            "ppid": 1,
            "state": "R",
            "cpu": 100,
            "command": "/usr/bin/clang++ source.cpp",
        },
        {
            "pid": 202,
            "ppid": 1,
            "state": "S",
            "cpu": 0,
            "command": "python -m arena.run other/config other/output",
        },
        {
            "pid": 203,
            "ppid": 1,
            "state": "Z",
            "cpu": 0,
            "command": "python -m training.train data",
        },
    ]
    for pid, command in [
        (204, "python -m verification.performance evidence"),
        (205, "python -P -c import_runpy /archived/source training.train data"),
        (206, "python /archived/source/verification/native_build.py evidence"),
        (207, "ctest --test-dir build"),
        (209, "python -m training.data_profile --dataset data"),
        (210, "python -m tools.plot_data_profile observations.json"),
    ]:
        rows.append(
            {"pid": pid, "ppid": 1, "state": "R", "cpu": 100, "command": command}
        )
    rows.append(
        {
            "pid": 208,
            "ppid": 100,
            "state": "R",
            "cpu": 100,
            "command": "python -P -c import_runpy /archived/source arena.run own/config",
        }
    )
    assert [row["pid"] for row in offenders(rows, 100)] == [
        200,
        201,
        202,
        204,
        205,
        206,
        207,
        209,
        210,
    ]
    with tempfile.TemporaryDirectory(prefix="caissa-strength-ceilings-") as folder:
        base = Path(folder)
        data = base / "model"
        data.mkdir()
        try:
            RecoveryScope(base / "default-too-long", {}, 43200, data, 0, 1)
        except ValueError:
            rejected.append("default corpus/model scope cannot grant twelve hours")
        else:
            raise AssertionError("existing six-hour authorization widened")
        first = RecoveryScope(
            base / "arena",
            {"sample": 4000},
            43200,
            data,
            0,
            1,
            maximum_authorized_seconds=43200,
        )
        original = (first.root / "SCOPE.json").read_bytes()
        deadline = first.deadline
        first.close()
        resumed = RecoveryScope(
            base / "arena",
            {"sample": 4000},
            43200,
            data,
            0,
            1,
            resume=True,
            maximum_authorized_seconds=43200,
        )
        assert (
            resumed.deadline == deadline
            and (resumed.root / "SCOPE.json").read_bytes() == original
        )
        resumed.close()
        try:
            RecoveryScope(
                base / "arena",
                {"sample": 3998},
                43200,
                data,
                0,
                1,
                resume=True,
                maximum_authorized_seconds=43200,
            )
        except ValueError:
            rejected.append("resumed fixed sample cannot change")
        else:
            raise AssertionError("resumed sample identity changed")
    live = offenders(process_rows(), os.getpid())
    print(
        json.dumps(
            {
                "status": "passed",
                "rejected": rejected,
                "unchanged_classical_control": True,
                "live_conflicting_processes": live,
                "scope": "contract and host-isolation checks; no full strength games executed",
                "full_acceptance": False,
            }
        )
    )


if __name__ == "__main__":
    main()
