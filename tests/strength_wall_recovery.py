"""Small lease and committed-game recovery controls, never a strength sample."""

import json
import tempfile
import time
from pathlib import Path
from unittest.mock import patch

from arena.run import game, pair
from tools.campaign_process import atomic
from tools.strength_wall_recovery import (
    WATCHER,
    CombinedScope,
    pin_journals,
    verify_journals,
)


def main():
    cases = []
    with tempfile.TemporaryDirectory(prefix="caissa-wall-controls-") as directory:
        base = Path(directory)
        old, data = base / "original", base / "model"
        old.mkdir()
        data.mkdir()
        origin = time.time() - 30
        state = {
            "deadline_unix": origin,
            "maximum_additional_bytes": 1024**2,
            "minimum_free_bytes": 0,
            "data_root": str(data),
            "initial_data_bytes": 0,
        }
        bindings = {"original_active_seconds": 41000.0, "original_attempts": 1}
        output = base / "recovery"
        lease = CombinedScope(output, old, state, bindings)
        original_scope = (output / "SCOPE.json").read_bytes()
        assert lease.deadline == origin + 18000 and 0 < lease.remaining() <= 2200
        cases.append("wall origin is old deadline; original active seconds charged")
        try:
            CombinedScope(output, old, state, bindings, resume=True)
        except BlockingIOError:
            cases.append("concurrent recovery owner refused")
        else:
            raise AssertionError("duplicate recovery owner admitted")
        lease.close()
        closed = json.loads((output / "ACTIVE_USAGE.json").read_text())
        assert closed["closed"] and closed["combined_active_seconds"] >= 41000
        lease = CombinedScope(output, old, state, bindings, resume=True)
        assert lease.active_used >= closed["recovery_active_seconds"]
        assert (output / "SCOPE.json").read_bytes() == original_scope
        lease.close()
        cases.append("resume retains wall bytes and cumulative recovery compute")

        def rejected(name, change, match):
            altered = {**state, **change}
            try:
                CombinedScope(output, old, altered, bindings, resume=True)
            except ValueError as error:
                assert match in str(error), (name, str(error))
                cases.append(name)
            else:
                raise AssertionError(name + " accepted")

        rejected(
            "wall renewal refused", {"deadline_unix": origin + 30}, "scope changed"
        )
        rejected(
            "disk renewal refused",
            {"maximum_additional_bytes": 2 * 1024**2},
            "scope changed",
        )
        for key, value in [
            ("original_active_seconds", 43200),
            ("original_attempts", 3),
        ]:
            try:
                CombinedScope(base / key, old, state, {**bindings, key: value})
            except ValueError:
                cases.append(key + " exhausted refused")
            else:
                raise AssertionError("exhausted combined resource admitted")
        with patch(
            "tools.strength_wall_recovery.time.time", return_value=origin + 18001
        ):
            try:
                CombinedScope(output, old, state, bindings, resume=True)
            except TimeoutError:
                cases.append("expired contiguous recovery refused")
            else:
                raise AssertionError("expired recovery admitted")

        # Simulate an unclosed ledger and prove elapsed active time is charged.
        stale = {**closed, "closed": False, "monotonic_stamp": time.monotonic() - 2}
        atomic(output / "ACTIVE_USAGE.json", stale)
        lease = CombinedScope(output, old, state, bindings, resume=True)
        assert lease.active_used >= stale["recovery_active_seconds"] + 1.9
        cases.append("unclosed ledger elapsed compute charged")

        arena = old / "neural"
        (arena / "games").mkdir(parents=True)
        (arena / "pairs").mkdir()
        config = {
            "candidate": {"command": ["/never-start-this"]},
            "opponent": {"command": ["/never-start-this-either"]},
        }
        opening = {"id": "metadata-fixture"}
        for reverse in [0, 1]:
            path = arena / "games" / f"000000-{reverse}.json"
            atomic(path, {"reverse": reverse, "metadata_control_only": True})
            path.with_suffix(".pgn").write_text(
                "metadata fixture, not scientific evidence\n"
            )
        before = {p: p.read_bytes() for p in (arena / "games").iterdir()}
        with patch(
            "arena.run.UciClient",
            side_effect=AssertionError("completed game was rerun"),
        ):
            assert game(config, opening, 0, 0, arena)["reverse"] == 0
            assert len(pair(config, opening, 0, arena)["games"]) == 2
        assert all(path.read_bytes() == value for path, value in before.items())
        cases.append(
            "both committed games reconstruct missing pair without starting an engine"
        )
        (arena / "games/partial.json.tmp").write_text("interrupted bytes")
        pins = pin_journals(old, output, lease)
        assert (
            output / "retained-partials/games/partial.json.tmp"
        ).read_text() == "interrupted bytes"
        verify_journals(old, pins, lease)
        (arena / "games/000000-0.json").write_text("changed completed game")
        try:
            verify_journals(old, pins, lease)
        except ValueError:
            cases.append("completed-game mutation rejected; interrupted bytes retained")
        else:
            raise AssertionError("changed original game admitted")
        watcher = old.parent / Path(WATCHER).name
        watcher.mkdir()
        (watcher / "allocated").write_bytes(b"x" * (1024**2 + 1))
        lease.last_size = -float("inf")
        try:
            lease.check()
        except ValueError as error:
            assert "disk ceiling" in str(error)
            cases.append("watcher source allocation is charged to the same combined disk cap")
        else:
            raise AssertionError("watcher allocation escaped combined disk budget")
        lease.close()
    print(
        json.dumps(
            {
                "status": "passed",
                "controls": cases,
                "strength_sample_certified": False,
                "full_acceptance": False,
            }
        )
    )


if __name__ == "__main__":
    main()
