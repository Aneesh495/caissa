# Final external-strength report binding

The original v4 external sample passed independent replay for all 2,000 games. This new report joins that accepted result, its seven actual stage exits and closed owner to the same saved engine and network used by the completed core checks. All 69 current native input hashes and modes still match the accepted compiled-source boundary. No new games, moves, native processes or bootstrap estimates ran.

| Opponent setting | Games | Pairs | Wins / draws / losses | Relative Elo | 95% interval |
|---|---:|---:|---:|---:|---|
| Stockfish 19 Skill Level 0 | 668 | 334 | 656 / 5 / 7 | +736.33 | [+649.70, +867.45] |
| Stockfish 19 UCI_Elo 2000 | 666 | 333 | 372 / 23 / 271 | +53.10 | [+30.33, +75.78] |
| Stockfish 19 unrestricted | 666 | 333 | 56 / 2 / 608 | -411.50 | [-460.14, -370.68] |

These are three separate comparisons. Stockfish's Skill Level and UCI_Elo option names do not establish calibrated absolute ratings. None of these values measures the public default classical configuration or a human rating.

The measured Caissa actor is executable `1ff25a97b2272f589aac40049f9c76e53228a3682f64489c72566dae449a9897`, network `52d0306143392ad683c3ebb09fe013f34e1f9e2bc44d3aa153b32314207374b7`. Options were Threads=1, Hash=16 MiB, Use Neural=true, Neural Weight=10, Lazy Neural=true, Evaluation Cache=true, Tactical Generation=true, Ordering Hints=false and Neural Bounds=false. The recorded opponent is Stockfish 19, SHA256 `dc2f18c34ae962dff591b66147d220ec06e61d756b93d8a4f5e04fd8e55c251f`; each setting used Threads=1 and Hash=16 MiB. `EXTERNAL_REPORT.json` records the precise opponent options.

Conditions were 100 ms per move, one-node warmup, 150 ms transport allowance, 512-ply maximum and two arena workers. This is a per-move budget, not a game clock. The accepted 95% intervals use 20,000 bootstrap resamples of opening families containing color-reversed pairs, seed 104729. All original outcomes remain included; there were zero unfinished games in each external subset. The original host receipt records `macOS-26.7.2-arm64-arm-64bit` and eight logical CPUs. It did not capture CPU brand or RAM, which remain unspecified for exact historical attribution. No raw process log was published.

The original campaign controller source is `9f3ac86ca38eb28b357ad7ef146f1af4bfb96021`, and the saved image's native input reference is `5803cc485420b19eb96dda2c29f81fcfc6b09b6b`. This report checked the current native boundary at product source `3f6fcb51742e0abf40eea68506ca0f24e6354ff3` against the [accepted core join](../final-core-runtime-join-2026-10-28/README.md). Matching the image and native inputs does not supply its missing original compiler/runtime closure.

All 2,000 retained local PGNs were hashed and their headers independently recounted. Their outcomes, opponent labels and 334/333/333 color-paired opening inventories match the accepted results. Original per-move JSON/pair journals and archived actor configurations are unavailable in the retained campaign tree. The old publication's raw-retention sentence describes its publication date; it is not current availability. This compact report does not contain the raw PGNs, perform another move replay or reproduce the retired full raw sample.

Eight focused controls rejected an absolute rating, a default-classical rating, a release flag, a different engine, public defaults substituted for the measured neural settings, a changed time budget, an unfinished original game and a changed opponent. A new one-invocation scope bound 2,099 inputs, 20 seconds and 2 MB; actual owner time was 0.20486041699768975 seconds with empty stderr. R07's report fields are checked. Full coordinator integration, original compiler/runtime provenance, the failed neural-gain requirement and release remain separate open work.
