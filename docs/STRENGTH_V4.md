# Saved v4 actor strength

The fixed external sample completed all 2,000 games and passed independent replay. The [final external report binding](../results/final-external-report-2026-10-28/README.md) checks its exact actor, settings, original stage exits, current native source boundary and retained PGN outcomes. Both v4 scopes are closed. Their samples are never restarted, extended or relabeled.

| Opponent setting | Games | Pairs | Wins / draws / losses | Relative Elo | 95% interval |
|---|---:|---:|---:|---:|---|
| Stockfish 19 Skill Level 0 | 668 | 334 | 656 / 5 / 7 | +736.33 | [+649.70, +867.45] |
| Stockfish 19 UCI_Elo 2000 | 666 | 333 | 372 / 23 / 271 | +53.10 | [+30.33, +75.78] |
| Stockfish 19 unrestricted | 666 | 333 | 56 / 2 / 608 | -411.50 | [-460.14, -370.68] |

These are three separate comparisons. Stockfish's Skill Level and UCI_Elo option names do not establish calibrated absolute ratings. None of these values measures the public default classical configuration or a human rating.

The measured Caissa actor is executable `1ff25a97b2272f589aac40049f9c76e53228a3682f64489c72566dae449a9897`, network `52d0306143392ad683c3ebb09fe013f34e1f9e2bc44d3aa153b32314207374b7`. Options were Threads=1, Hash=16 MiB, Use Neural=true, Neural Weight=10, Lazy Neural=true, Evaluation Cache=true, Tactical Generation=true, Ordering Hints=false and Neural Bounds=false. The recorded opponent is Stockfish 19, SHA256 `dc2f18c34ae962dff591b66147d220ec06e61d756b93d8a4f5e04fd8e55c251f`; each setting used Threads=1 and Hash=16 MiB. `EXTERNAL_REPORT.json` records the precise opponent options.

Conditions were 100 ms per move, one-node warmup, 150 ms transport allowance, 512-ply maximum and two arena workers. This is a per-move budget, not a game clock. The accepted 95% intervals use 20,000 bootstrap resamples of opening families containing color-reversed pairs, seed 104729. All original outcomes remain included; there were zero unfinished games in each external subset. The original host receipt records `macOS-26.7.2-arm64-arm-64bit` and eight logical CPUs. It did not capture CPU brand or RAM, which remain unspecified for exact historical attribution. No raw process log was published.

The same executable advertises public defaults of one thread, 32 MiB hash and neural evaluation disabled. Those declarations came from the accepted G04 transcript. The external games above deliberately used 16 MiB and the frozen neural mixture. No measured absolute, default-classical or human rating is established. Nominal Stockfish option labels cannot supply one.

The selected floating checkpoint remains C76 from validation-only seed 73 at step 2750. The q4096 network is 52d, and the saved executable is 1ff. The original learning receipt remains unchanged. The [core runtime join](../results/final-core-runtime-join-2026-10-28/README.md) checks the final identity and native inputs; original compiler/runtime closure and complete coordinator acceptance remain open.

The original v4 neural comparison recorded 4,000 attempts, 3,997 finished games and three original 512-ply-limit records. Independent full-sample acceptance failed. Its completed-game diagnostic was -63.86 relative Elo against unchanged classical evaluation, with a 95% interval of [-73.80, -54.07]. The required 50 Elo gain and positive lower bound remain unmet. No checkpoint, seed or mixture is selected from match outcomes to replace that failure.

Earlier q1024 numerical and neural-gain failures remain preserved under their original actors. The later 52d numerical component passed its separate frozen endpoint; that does not repair a strength failure or rewrite an old model receipt.

The current tree retains the 2,000 external PGNs. The new report hashes them and recounts only headers, outcomes and color pairs. It reuses the accepted historical uncertainty and full independent move replay. Original game JSON, pair journals and archived actor configurations were retired, so a fresh full raw replay from this compact package is unavailable. Historical publication receipts remain unchanged and describe their original date. [Retention policy](ARTIFACT_RETENTION.md) states the present limits.

The historical scope admitted at most three attempts and one 12-hour wall/active ceiling per domain under the original parent. Those closed limits are unchanged and grant no additional games. No rating producer is currently admitted. The [prospective rating benchmark](RATING_BENCHMARK_DESIGN.md) still requires real game-clock support, defensible calibration and a new feasible finite scope.
