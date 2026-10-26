# Battery operation and optional power waiting

The user authorized background work to continue on battery. New controllers
using default `POLICY` allow AC and battery, record power state and retain their
scoped awake assertion. Unplugging alone neither pauses nor aborts these jobs.
Deadlines and attempt limits remain unchanged. Historical archived controllers
and retained failures are not rewritten. `STRICT_AC_POLICY` remains an explicit
option for separately declared controlled work; it is not the new default.

New arena jobs can declare a `power_wait` object in their immutable configuration:

```json
{"power_wait": {"mode": "wait-between-moves-v1", "deadline_unix": 1793058983.7196429}}
```

The deadline is an externally chosen original absolute limit, not a duration
renewed on each resume. The example is illustrative, not authorization to start
or change an experiment. The arena checks AC before engine startup, at every new
game and before another search. On battery it waits, then continues automatically
when AC returns. A search already in flight finishes normally; engines are never
suspended in the middle of their clocks. Waiting happens before `UciClient.play`
starts its move clock, so moving rooms does not become a time-forfeit result.
Power is sampled at most once per second during a game and freshly at each game
boundary. This is a prospective power policy, not proof of uninterrupted AC
through every search.

`POWER_WAIT_POLICY.json` binds the original deadline. State changes and cumulative
wait time are explicit in `POWER_WAIT_EVENTS.jsonl` and `POWER_WAIT_PROGRESS.json`.
Unknown power state waits too. The deadline keeps advancing on battery and an
exhausted wait cannot be revived by restarting or changing its output metadata.
No new campaign attempt is consumed merely by an unplug/replug cycle.

An owning controller must also opt into `tools.power_guard.WAIT_POLICY` so its
outer monitor does not abort the arena while it waits. This retains the scoped
awake assertion and power observations. Default `POLICY` permits battery operation. Existing frozen owner archives, match profiles,
deadlines, failures and attempt ceilings are not changed or hot-patched.

The targeted power-boundary workflow is a new diagnostic domain. Its power
transitions are injected, and its four native one-move mate games are integration
checks, not strength measurements. It never reruns browser, training, recovery or
closed strength campaigns. Full project acceptance remains separate.

The user also authorized normal laptop use during background work. New
`HostGuard` callers now record competing process metadata without aborting by
default. `require_idle=True` is available only as an explicitly selected stricter
policy. Every new host sample records `idle_required`; process arguments remain
omitted. Results gathered during normal use must retain their actual load/power
records and cannot be represented as controlled-idle measurements. The exclusive
Caissa lease still prevents two of our heavy campaigns from claiming the host
simultaneously. Remote checks can continue independently.
