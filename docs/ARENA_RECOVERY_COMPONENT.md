# Arena recovery evidence

The isolated G11 arena component kills a real arena process after it commits
one authoritative game JSON and before it exports that game's PGN or starts
the reversed-color partner. The opt-in failpoint has a 30-second timeout and
is restricted to a two-pair, 2,000-node recovery diagnostic. Strength profiles
cannot enable it. Normal arena execution uses the existing default path.

`tools.arena_recovery` captures the actual SIGKILL exit, protected game bytes,
boundary identity and two deliberately torn temporary writes. It resumes the
same arena configuration, repairs the missing PGN and finishes the partner
games. Its single experiment has a 120-second wall/active ceiling, a 128 MiB
additional output cap and a 10 GiB free-space reserve. Existing output cannot
be overwritten to obtain another attempt.

`verification.arena_recovery` independently reads the boundary bytes and raw
signal record, checks unchanged resources/actors, reconstructs all four games,
their PGNs and legal principal variations, and recomputes paired statistics.
Its independent native probe seeds a new owned directory with the protected
game and torn writes, runs the saved program to recover the three missing
games, and checks unchanged protected bytes and deterministic moves/results.
Raw replay alone cannot mark this component passed without that native probe.
It never trusts a saved recovery-pass boolean. Every original artifact remains
unchanged during replay.

The immutable full-bundle adapter stages every declared raw artifact and runs
the same independent reader. It reports an arena component only. G11 remains
pending until training and original-data/split recovery are independently
reconstructed. These four diagnostic games establish no playing-strength gain
and never enter the full learning or strength corpora.
