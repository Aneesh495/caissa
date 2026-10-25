# Full original external comparison

All 2000 games completed and passed independent replay. There were no illegal
moves, crashes, time/protocol forfeits or unfinished games. This result belongs
to the original q1024 candidate, not the later q4096/deferred implementation.

| Stockfish 19 configuration | Games | Caissa W/D/L | Relative Elo | 95% interval |
|---|---|---|---|---|
| Skill Level 0 | 668 | 657/7/4 | +777.92 | [+687.87,+911.37] |
| UCI_Elo 2000 | 666 | 359/53/254 | +55.24 | [+33.49,+76.87] |
| Unrestricted | 666 | 59/8/599 | -392.39 | [-438.13,-353.45] |

The option names identify tested configurations. They do not calibrate an
absolute rating. Caissa's absolute Elo remains unestablished. The unrestricted
comparison does not support a Stockfish parity claim.

The frozen conditions were 100 ms per move, one thread, 16 MiB hash, two arena
workers, a one-node warmup and 150 ms transport allowance. The unchanged
held-out opening families were played with reversed colors, with a 512-ply
ceiling and complete native UCI/PV observations. Confidence intervals use
20000 opening-family bootstrap resamples with seed 104729. All actual outcomes
and failures enter the statistics. These estimates apply to this opening and
resource protocol, not a human online rating or another time control.

The candidate executable is
`49057cfe1b03077c49085225cfb5e9dde7cead86c9dda92b6d6c3f9a60505da2`.
Its original network is
`c251670ec53ba38a680c16cc6199be48f89cc829dd5483197e6d4b39ac6debf6`,
with the validation-selected seed 73, step 2750 and ten-percent mixture.
Stockfish is solely an external comparator, pinned as
`dc2f18c34ae962dff591b66147d220ec06e61d756b93d8a4f5e04fd8e55c251f`.
Both candidate artifacts are saved beside this report. No external engine or
network is part of Caissa's implementation or inference.

Owner source `a425ef7a963cffb35f081a7dd333a17d25dd6aa8` finished at
Unix time 1792924509.690625, within its original 43200-second deadline
1792959695.442284. The scope is closed. `INDEPENDENT.json` reconstructs every
game, actor option, legal PV and statistical endpoint. The actual successful
independent stage exit and its output hash are retained.

[Complete portable raw evidence](../strength-raw-v3-2026-10-25/README.md)
contains every pair, game journal and PGN for these 2000 games and the earlier
4000-game neural comparison. Saved summaries are not substitutes for those
observations. The original neural model still lost 61.97 Elo against its
unchanged classical control and failed G08. Its numerical failure also remains
failed. The newer encoding and deferred implementation need their own frozen
strength tests. Final systems, browser, reproduction and whole-project gates
remain incomplete, so this is not a release or final engine rating.
