# Draw-history replay

The `rules` command in `caissa --state-probe NETWORK` reads the current native
position. It reports the actual terminal reason, threefold/fifty-move claim
flags, intended-move claims, conservative dead-material decision and all three
rule-overload results. It also verifies that intended-move inspection restores
the complete board, history and search identity. The new command preserves
the existing state response.

[The frozen profile](../config/draw-history-v1.json) specifies28 fixed histories
and64 seeded reachable walks of at most32 plies. Fixed cases include identical
FENs with different repetition histories, threefold versus fivefold, intended
claims, reversible transpositions, synthetic null branches, clocks98/99/100
and149/150/151, mate/stalemate precedence, legal/pinned en passant, captures,
pawn resets, Chess960 castling and conservative dead-material boundaries.
The producer has180seconds and the independent replay240seconds. Raw output
is limited to16MiB and10000 observations. Every fixed case and complete seeded
walk is required; a truncated prefix cannot satisfy G03.

[The independent verifier](../verification/draw_history.py) evolves its own
python-chess board and history. It computes terminal and current/intended
claim decisions independently, reconstructs native hash identities, checks
exact JSON types and reexecutes every request through the pinned saved
native program. It requires actual witnesses of different threefold and
fivefold decisions for equal FENs and distinct context keys for transposed
histories. All six terminal outcomes must occur. Saved success flags cannot
replace these observations.

The full-bundle G03 driver is `draw-history-v1`. Its `draw_history` object names
four distinct declared raw references: `profile`, `config`, `summary` and
`observations`. Source, program and network identities must match the full
deployment, and replay output must stay outside the original evidence.
Completing G03 alone leaves every other semantic gate pending.

[The controls](../tests/draw_history.py) execute the actual producer and
independent CLI, then rehash altered claim flags, automatic decisions,
synthetic-null claims, intended moves, boolean counters, context keys, schedule
indices, removed observations and false counts. They exercise the real full
entry as well as missing, aliased and internal-output artifact rejection.
This checks rule semantics. It provides no playing-strength measurement.
