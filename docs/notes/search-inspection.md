# Browser search inspection

The analysis room has an optional inspector for the original native engine's final counters and sampled search positions. It is disabled initially. Normal analysis requests keep `Search Stats=false` and `Trace Samples=0`. Inspection requests enable statistics and at most eight samples per worker, with the service's existing four-thread maximum. They use the same position/history, classical evaluator, search switches and resource limits.

`analysis-service/telemetry.ts` interprets the actual UCI statistics and trace records. Counter names are finite and complete; duplicates, negative values, inexact integers and impossible node/table relationships are rejected. Trace fields have explicit depth, ply, window, FEN-length and delimiter limits. The service admits only a boolean inspection flag, emits one final summary and accepts at most eight samples per requested worker. Backpressure or malformed native telemetry cancels the owned search. The source interfaces are shared with the browser through type-only imports.

The browser displays total visited work separately from cumulative work through the last completed depth. The latter excludes the unfinished final iteration. Evaluator nanoseconds are summed across workers, so they are not a percentage of wall time. The average divides that sum by actual evaluator calls and handles an empty terminal search. Table hits, table cutoffs, beta/null cutoffs, reductions, re-searches, futility skips and cache/neural counters remain separate observations. They do not form mutually exclusive percentages or establish Elo.

Trace samples show depth, ply, alpha/beta in side-to-move centipawns, FEN and synthetic-null status. They are bounded inspection examples, not a complete search tree or a tactical proof. A FEN alone cannot recover the earlier repetition history. The inspector does not replace the user's game with a sample position.

Each new position or analysis clears prior counters and samples. Cancellation before the native summary explicitly reports that no completed summary is available. A terminal position can produce a valid zero-work summary. The checkbox supports keyboard toggling. Bounded DOM construction and text content avoid inserting raw engine text as HTML.

The native control compared a 10000-node search with tracing off/on. Completed-depth scores, PVs, best moves and all non-timing work counters matched. The actual service then emitted complete summaries and bounded samples with one and four threads, retained no inspection events in default mode, handled a zero-node checkmate, rejected an invalid request flag and cleaned up a cancelled 30-second analysis. Ten malformed native telemetry controls were rejected.

A fresh browser origin displayed the real counters and sixteen samples from two workers. Moving e2-e4 cleared them. A new long search was cancelled and displayed the missing-summary state. The 390-pixel layout had a 390-pixel document width, and keyboard off/on toggling cleared stale counters. The temporary viewport was reset and the temporary service/tab closed. The original browser session was not reset. These checks cover this development increment; final release-source browser acceptance remains required.

The first native probe timed out because its development driver omitted the initial `uci` request. Its original driver, failure and command record remain retained. Correcting that driver and completing the service/browser checks stayed within the original 1200-second development ceiling. No engine/model/data or decisive-match scope was restarted or extended.

The first publication check rejected the required blank event delimiter at the end of raw SSE captures. The format-specific Git attribute now preserves these bytes and permits that delimiter; it changes no source-code whitespace checks. The original publication failure and byte-identical captured streams remain retained.

[Raw native records, actual SSE streams, parser controls, browser state and screenshots](../../results/search-inspection-2026-10-25/) retain the observations and immutable byte identities. No playing-strength inference follows from these inspection counters.
