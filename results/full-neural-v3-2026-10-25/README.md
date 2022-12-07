# Full neural comparison: negative contribution

The selected original q1024 neural model lost strength against the unchanged classical evaluator under equal time. All 4000 games completed and were independently replayed. G08 failed its prospectively frozen endpoint.

| Observation | Result |
|---|---:|
| Color-reversed pairs | 2000 |
| Opening-family clusters | 1000 |
| Neural wins / draws / losses | 1274 / 746 / 1980 |
| Unfinished games | 0 |
| Crashes, illegal moves and time/protocol forfeits | 0 |
| Neural score | 0.41175 |
| Neural Elo difference versus classical | -61.9713 |
| Opening-cluster 95% interval | [-71.2512, -52.8671] |
| Required neural gain | At least +50, with 95% lower bound above zero |

Both actors used the identical original executable, one thread, 16 MiB hash, 100 ms per move, one warmup node and a 150 ms transport allowance. Color-reversed opening pairs were retained. Evaluation Cache and Tactical Generation were enabled for both actors; Neural Bounds and Ordering Hints were disabled. The candidate used the fixed ten-percent neural mixture. The control used the original classical contract 1. No baseline term, opening, seed, checkpoint, model weight or stopping rule was changed after results arrived.

The [frozen protocol](inputs/PROTOCOL.json), [owner scope](SCOPE.json), [arena configuration](ARENA_CONFIG.json), [summary](SUMMARY.json) and [actual independent rejection](INDEPENDENT.json) preserve the comparison. The independent verifier reconstructed every game, legal PV, UCI budget/history request, result color and terminal decision, then recomputed opening-family uncertainty with 20000 bootstrap resamples and seed 104729. Its [actual stage exit](INDEPENDENT_STAGE.json) is 1 because the predeclared strength requirement failed. The owner [completed the full sample with the failed gate](STRENGTH_CAMPAIGN.json); this is not a successful G08 result.

The exact saved executable and network are included. Engine SHA256 is `49057cfe1b03077c49085225cfb5e9dde7cead86c9dda92b6d6c3f9a60505da2`; network SHA256 is `c251670ec53ba38a680c16cc6199be48f89cc829dd5483197e6d4b39ac6debf6`. The engine was built from source `88937d913e5e97808a6e002bd8587c96633fc905`, while the immutable resumed match owner used `15fe3871ae723bd01106fe726be4a9630f5e683e`. The selected float checkpoint remains seed 73 at step 2750, SHA256 `c76d8e9ef0f2255531bc9085f5d0330a7a4152cf9b21a65ff8aee740ab8b2005`.

The [raw index](RAW_INDEX.json) hashes every retained pair/game journal and PGN. Their complete bytes remain immutable locally; portable bulk raw-game distribution is still pending. The manifest and compact receipts do not substitute for those raw files or for full fresh-checkout reproduction. The [publication check](PUBLICATION_CHECK.json) cross-checks the independent and producer observations and recomputes score-to-Elo arithmetic. It does not replace independent game replay.

Validation loss improved, but that did not establish stronger equal-time chess. This experiment alone cannot separate evaluation quality, quantization effects and search cost. The q1024 numerical failure remains failed. The later q4096 encoding passed separate numerical and instrumentation checks, but was not substituted into these games and has no measured strength yet.

Classical evaluation remains the default. The separately frozen 2000-game external comparison continues with the same original validation-selected q1024 candidate, including its failed learning-domain numerical and neural-contribution gates. It will not be silently replaced with another evaluator. This result is a relative score-to-Elo estimate under the named resources, not an absolute rating or evidence of Stockfish parity. No release or whole-project acceptance follows.
