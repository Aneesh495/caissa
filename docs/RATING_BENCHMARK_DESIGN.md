# Prospective Caissa rating benchmark

Status: design only, 2026-10-28. No match producer, additional parallel time, opponent download or new training is admitted by this document. The original parallel campaign remains closed and incomplete.

## What the result would mean

A usable estimate needs a declared engine configuration, a connected opponent pool, defensible calibration, independently checked games and uncertainty. A relative result against an unrestricted engine does not supply a human rating. Stockfish's own documentation explains that ratings depend on the opponents and playing conditions, including the time control and opening book. [Stockfish rating FAQ](https://official-stockfish.github.io/docs/stockfish-wiki/Stockfish-FAQ.html#the-elo-rating-of-stockfish)

The existing v4 neural result remains -411.50 relative Elo against unrestricted Stockfish 19. It does not rate the public classical default. Neither the failed neural-gain requirement nor the incomplete final multicore comparison is repaired by this proposed benchmark.

## Target identity

The primary proposed target is the retained `1ff25a97b2272f589aac40049f9c76e53228a3682f64489c72566dae449a9897` executable with the classical configuration advertised by its archived source: one thread, 32 MiB hash, neural evaluation off, one principal variation and pondering off. The archived source also advertises evaluation cache, tactical generation and lazy neural evaluation as off. A new bounded identity check must confirm the executable's complete option inventory before any benchmark admission. Source declarations alone do not prove runtime settings or compiler provenance.

This target follows the public default configuration. It is not a model selected from test outcomes. The saved neural actor remains a separate identity with network `52d0306143392ad683c3ebb09fe013f34e1f9e2bc44d3aa153b32314207374b7` and its unchanged ten-percent mixture. No new neural campaign is part of this design. The old studies used 16 MiB and different evaluator options, so their games cannot be pooled into the proposed default target's rating.

## Comparator and calibration

The retained Stockfish 19 installation has executable SHA256 `dc2f18c34ae962dff591b66147d220ec06e61d756b93d8a4f5e04fd8e55c251f`. Its bytes match the original comparator pin; no engine was downloaded or executed for this design.

The proposed local comparison pool contains the classical target and three configurations of this same comparator: `UCI_LimitStrength=true` with nominal `UCI_Elo` values 1600, 2200 and 2800. Each uses one thread, 32 MiB hash, one principal variation, pondering off and no tablebases. The settings are fixed design choices, not adaptations to new results. They are correlated configurations of one engine family, not three independent rated programs.

Stockfish documents its `UCI_Elo` calibration at **120 seconds plus one second per move**, anchored to CCRL 40/4. This does not validate interpreting a 100 ms per-move result on that scale. The advertised values must also be checked against the exact retained image's UCI inventory. [Stockfish UCI options](https://official-stockfish.github.io/docs/stockfish-wiki/UCI-Protocol-and-Stockfish-Commands.html#uci_elo)

An estimate conditional on a nominal Stockfish setting has sampling uncertainty and additional calibration uncertainty. If the latter cannot be bounded from independent evidence, publish relative pool results only and leave the calibrated rating milestone incomplete. Do not present a nominal option label as a measured human or official CCRL rating.

A separate CCRL-compatible route would need exact rated engine versions and comparable or independently calibrated conditions. CCRL describes hardware calibration, a common generic opening book and pondering off; its 40/15 list is not the same condition as the existing Caissa matches. No CCRL submission, new comparator acquisition or large tablebase download is authorized here. The CCRL pages were available through primary-source search excerpts; direct page retrieval was denied, so a complete local methodology snapshot was not obtained. [CCRL methodology](https://computerchess.org.uk/), [CCRL conditions](https://computerchess.org/about.html)

## Proposed fixed schedule and analysis

The four actors form six unordered edges. A functional calibration pilot would use five color-reversed opening pairs per edge, for 60 games. It would test clocks, records and obvious calibration inconsistencies; it would not by itself establish a precise rating. A separate full proposal uses 30 pairs per edge, for 360 games. Neither sample is admitted now, and a pilot cannot be silently extended into the full sample.

Freeze the opening identities, edge order, colors, configuration and analysis before play. Use deterministic indices from the retained opening inventory, with the same position and reversed colors within a pair. These openings have been used in earlier studies and must not be described as newly unseen data. Model, checkpoint, mixture and search options remain fixed throughout.

Fit the complete connected pool with an explicit draw model. Resample by opening identity, keeping both colors and all edges sharing that opening together. Report wins, draws, losses, time forfeits, unfinished records, the fitted relative ratings and 95% intervals. The analysis must reject disconnected or unidentifiable fits and report saturated results as bounds rather than inventing finite certainty. A proposed full-study precision criterion is a 95% half-width of at most 100 Elo, conditional on an independently justified calibration. Failure to reach precision is an incomplete estimate, not permission to add games or choose another target.

Clock losses remain results. Protocol failures and ply-limit records remain explicit failures; neither is replaced with a favorable game. A fixed safety ceiling of 512 plies is proposed. Do not adjudicate an unfinished game as a draw merely to finish the sample. No pooling with the historical 4,000/2,000-game campaigns or the multicore campaign is allowed.

## Implementation and admission prerequisites

1. Add actual per-player game clocks and increments to the match runner. The current `arena.client` sends node or `movetime` limits, while `arena.run` accepts exactly one of node and millisecond budgets. It does not yet implement this benchmark's 120+1 clocks.
2. Check full elapsed move time, increment application, clock exhaustion, cancellation and recovery with synthetic clock and transport controls before real games. Transport tolerance must not add free playing time to the game clock.
3. Bind native handshakes, all options, comparator bytes, source/runtime inputs, opening records, statistical code and the complete schedule in a new finite scope.
4. Establish the calibration evidence and its limits before displaying an anchored rating. The local Stockfish settings alone do not establish an official rating-list entry.
5. Check feasibility before admission. Even without transport or shutdown overhead, a 512-ply game can consume 240 initial clock seconds plus 512 increment seconds. The proposed full sample therefore needs substantially more worst-case time than remains under the present parent. It cannot be launched against an inadequate time budget with an assumed later renewal.
6. Meter all game, PGN, pair, summary, log and control writes before growth. Count the retained Homebrew Stockfish installation alongside the checkout, Python runtime and attributable caches. Enforce the 5 GB project and 400 GB whole-Mac limits, with no cloud upload or relocation workaround.
7. Use one actual host owner, a fixed deadline clipped to its genuinely authorized parent, immutable records and independent replay. A hard stop preserves the incomplete sample and every consumed allowance.

## Current decision

The design is written. The benchmark remains **not admitted**. Game clocks, a calibrated anchor with defensible uncertainty, independent rating analysis, native identity checks and a feasible fresh scope are still missing. Continue the final source and evidence joins while these requirements are unresolved. No absolute engine or human Elo is claimed.
