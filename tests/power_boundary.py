"""Real arena boundary waits plus finite deadline and immutable policy controls."""

import argparse
import json
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from arena.power_wait import PowerWait


class FakeTime:
    def __init__(self):
        self.now = 100.0

    def clock(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


class Boundaries(unittest.TestCase):
    def test_waits_resume_automatically_and_deadline_keeps_running(self):
        with tempfile.TemporaryDirectory() as directory:
            clock = FakeTime()
            gate = PowerWait(
                directory,
                {"mode": "wait-between-moves-v1", "deadline_unix": 110},
                clock=clock.clock,
                sleeper=clock.sleep,
                observer=lambda: {"ac_power": clock.now >= 103},
            )
            gate.before_work()
            self.assertEqual(clock.now, 103)
            self.assertEqual(gate.waited, 3)
            gate.observe = lambda: {"ac_power": False}
            clock.now += 1
            with self.assertRaisesRegex(ValueError, "original deadline"):
                gate.before_work()
            self.assertEqual(clock.now, 110)
            events = [
                json.loads(line)["state"]
                for line in (Path(directory) / "POWER_WAIT_EVENTS.jsonl")
                .read_text()
                .splitlines()
            ]
            self.assertEqual(
                events,
                [
                    "waiting-for-ac",
                    "resumed-on-ac",
                    "waiting-for-ac",
                    "deadline-exhausted",
                ],
            )

    def test_resume_cannot_extend_saved_deadline_or_follow_policy_link(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            clock = FakeTime()
            PowerWait(
                root,
                {"mode": "wait-between-moves-v1", "deadline_unix": 110},
                clock=clock.clock,
            )
            before = (root / "POWER_WAIT_POLICY.json").read_bytes()
            with self.assertRaisesRegex(ValueError, "deadline changed"):
                PowerWait(
                    root,
                    {"mode": "wait-between-moves-v1", "deadline_unix": 111},
                    clock=clock.clock,
                )
            self.assertEqual((root / "POWER_WAIT_POLICY.json").read_bytes(), before)
            (root / "POWER_WAIT_POLICY.json").rename(root / "preserved")
            (root / "POWER_WAIT_POLICY.json").symlink_to(root / "preserved")
            with self.assertRaisesRegex(ValueError, "deadline changed"):
                PowerWait(
                    root,
                    {"mode": "wait-between-moves-v1", "deadline_unix": 110},
                    clock=clock.clock,
                )

    def test_unknown_power_waits_rather_than_starting_work(self):
        from tools.power_guard import POLICY, STRICT_AC_POLICY, WAIT_POLICY, PowerGuard

        with (
            patch("tools.power_guard.sys.platform", "darwin"),
            patch("tools.power_guard.observe", return_value={"ac_power": False}),
        ):
            with self.assertRaisesRegex(ValueError, "plug Mac"):
                PowerGuard(STRICT_AC_POLICY)
            self.assertFalse(PowerGuard(POLICY).admission["ac_power"])
            with tempfile.TemporaryDirectory() as directory:
                from unittest.mock import Mock

                guard = PowerGuard(POLICY)
                guard.output = Path(directory)
                guard.helper = Mock()
                guard.helper.poll.return_value = None
                guard.check()
                self.assertFalse(
                    json.loads((Path(directory) / "POWER_SAMPLES.jsonl").read_text())[
                        "ac_power"
                    ]
                )
            self.assertFalse(PowerGuard(WAIT_POLICY).admission["ac_power"])
        from tools.full_strength import HostGuard
        from unittest.mock import Mock

        with tempfile.TemporaryDirectory() as directory:
            rows = [
                {
                    "pid": 2,
                    "ppid": 1,
                    "state": "S",
                    "cpu": 60,
                    "command": "clang --token=SYNTHETIC",
                }
            ]
            with (
                patch("tools.full_strength.process_rows", return_value=rows),
                patch("tools.full_strength.os.getpid", return_value=900000),
            ):
                HostGuard(Path(directory), Mock()).check()
            snapshot = (Path(directory) / "HOST_SAMPLES.jsonl").read_text()
            self.assertFalse(json.loads(snapshot)["idle_required"])
            self.assertEqual(json.loads(snapshot)["offenders"][0]["pid"], 2)
            self.assertNotIn("SYNTHETIC", snapshot)
        with tempfile.TemporaryDirectory() as directory:
            clock = FakeTime()

            def unknown():
                raise ValueError("power unavailable")

            gate = PowerWait(
                directory,
                {"mode": "wait-between-moves-v1", "deadline_unix": 102},
                clock=clock.clock,
                sleeper=clock.sleep,
                observer=unknown,
            )
            with self.assertRaisesRegex(ValueError, "original deadline"):
                gate.before_work()
            self.assertEqual(clock.now, 102)


def native_case(engine, output):
    from arena.run import main as arena_main

    output.mkdir(parents=True, exist_ok=False)
    openings = output / "openings.json"
    openings.write_text(
        json.dumps(
            {
                "openings": [
                    {
                        "id": "power-mate-white",
                        "fen": "7k/5Q2/6K1/8/8/8/8/8 w - - 0 1",
                        "moves": [],
                    },
                    {
                        "id": "power-mate-black",
                        "fen": "8/8/8/8/8/6k1/5q2/7K b - - 0 1",
                        "moves": [],
                    },
                ]
            }
        )
    )
    config = {
        "profile": "power-boundary-diagnostic-v1",
        "candidate": {
            "name": "original Caissa A",
            "command": [str(engine)],
            "options": {"Threads": 1, "Hash": 16},
        },
        "opponent": {
            "name": "original Caissa B",
            "command": [str(engine)],
            "options": {"Threads": 1, "Hash": 16},
        },
        "openings": str(openings),
        "pairs": 2,
        "max_plies": 64,
        "milliseconds": 100,
        "transport_allowance_ms": 1000,
        "power_wait": {
            "mode": "wait-between-moves-v1",
            "deadline_unix": time.time() + 90,
        },
    }
    path = output / "config.json"
    path.write_text(json.dumps(config))
    arena = output / "arena"
    # Simulate an unplug while a move is about to start, not a SIGSTOP of clocks.
    original_play = __import__("arena.client", fromlist=["UciClient"]).UciClient.play
    searches = 0
    unplug_at = None

    def play(client, *args, **kwargs):
        nonlocal searches, unplug_at
        searches += 1
        if searches == 1:
            unplug_at = time.time()
        return original_play(client, *args, **kwargs)

    def observed():
        return {"ac_power": unplug_at is None or time.time() - unplug_at >= 2}

    started = time.monotonic()
    argv = ["arena.run", str(path), str(arena), "--workers", "1"]
    with (
        patch("sys.argv", argv),
        patch("arena.power_wait.observe", side_effect=observed),
        patch("arena.client.UciClient.play", play),
    ):
        arena_main()
    games = sorted((arena / "games").glob("*.json"))
    assert len(games) == 4 and searches == 4
    rows = [json.loads(p.read_text()) for p in games]
    assert all(
        row["termination"] == "checkmate" and row["result"] in ("1-0", "0-1")
        for row in rows
    )
    assert all(
        all(turn["milliseconds"] < 1100 for turn in row["observations"]) for row in rows
    )
    events = [
        json.loads(line)
        for line in (arena / "POWER_WAIT_EVENTS.jsonl").read_text().splitlines()
    ]
    assert [row["state"] for row in events] == ["waiting-for-ac", "resumed-on-ac"]
    assert events[-1]["waited_seconds"] >= 1
    before = {p.name: p.read_bytes() for p in games}
    with (
        patch("sys.argv", argv),
        patch("arena.power_wait.observe", return_value={"ac_power": True}),
    ):
        arena_main()
    assert all(p.read_bytes() == before[p.name] for p in games)
    print(
        json.dumps(
            {
                "status": "passed power-boundary diagnostic",
                "native_games": 4,
                "new_games_on_resume": 0,
                "seconds": time.monotonic() - started,
                "waited_seconds": events[-1]["waited_seconds"],
                "strength_sample": False,
                "full_acceptance": False,
            }
        )
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--engine", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    tests = unittest.TextTestRunner(verbosity=2).run(
        unittest.defaultTestLoader.loadTestsFromTestCase(Boundaries)
    )
    if not tests.wasSuccessful():
        return 1
    native_case(args.engine.resolve(), args.output.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
