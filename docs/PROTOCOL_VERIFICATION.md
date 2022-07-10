# Independent protocol replay

`python -m tools.protocol_audit` runs the bounded producer. Its version-two
transcript records each command immediately before writing to the native pipe
and each response after the bounded reader queue. Stop latency is the difference
between those recorded timestamps. The same observations therefore support
independent percentile reconstruction, including scheduling and transport time.

`python -m verification.protocol RUN --engine-sha256 SHA --full` reads the saved
transcript without executing the producer or engine. It checks the UCI lifecycle,
readiness barriers, active-search ownership, stop requests, immediate ponderhit,
thread changes, malformed-command errors, every best move, every principal
variation, optional ponder replies, monotonic clocks, sample sizes and the exact
reported latency percentiles. Its full mode requires at least 10000 ordinary
sequences, all four search modes and thread settings, 100 ponder sequences and
stop p99 strictly below 50 ms. Passing this domain checker does not certify the
remaining project gates or source identity by itself.

The development sample on executable `f7476637` completed 10000 sequences and
100 ponder requests. Separate replay checked 3435 legal principal variations,
10100 best moves and 2611 expected negative-control errors. Stop p99 was
8.467125 ms; the maximum was 158.520167 ms. The endpoint concerns the percentile,
so this result does not claim that every stop completed within 50 ms. Eight data
workers and preparation were active on the same host.

Six semantic mutations, each with a freshly recomputed transcript hash, were
rejected: an illegal best move, a null move in a playable position, a missing
stop request, a false latency percentile, an illegal principal variation and a
clock regression. The 300-sequence pilot was refused as full evidence. A real
one-second timeout retained its partial transcript and failed summary, stopped
after 192 sequences and reaped the native process with exit -9.

The initial checker rejected the unchanged 300-sequence pilot because it did
not support UCI's optional `bestmove ... ponder ...` fields. The corrected parser
accepts that standard form and independently checks the reply's legality after
the best move. Both the original rejection and the successful replay are kept.
This was a checker correction, not a change to the native evidence or endpoint.

Raw transcripts, summaries, commands and semantic rejections are retained under
`results/protocol-replay-2026-10-23`. The saved native executable corresponds to
the preceding bounds development source. Final acceptance must repeat the
campaign on the final executable and bind that source independently.
