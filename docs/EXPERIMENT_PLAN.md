# Experiment protocol v1

This protocol separates diagnostic development from decisive full experiments. Full acceptance is pending. Date: 2026-10-22. Host: Apple arm64, 8 logical cores, 16 GiB unified memory. CPU is the reproducible training backend; MPS is available but is a separate exploratory profile. No paid resources are allocated.

## Correctness prerequisites

Before corpus generation: 20 frozen independent perft fixtures, 100000 external reachable-position move comparisons, 1000000 reversible transitions with full accumulator refresh and scalar/native parity, history-sensitive draw cases, exhaustive tiny search trees and 10000 adversarial protocol sequences. Preserve the actual source and executable identities of the teacher. Changes to chess legality invalidate affected corpus data. Changes to a later candidate search do not rewrite the historical original teacher's labels.

## Full resource ceiling and corpus

Generate 200000 opening pairs, at most 400000 games, using the original classical teacher with 500 nodes per move, one thread and 4 MiB hash per process. Four concurrent workers are the default ceiling. Maximum 512 plies per game. A 512-ply exhaustion is unfinished and receives no outcome target. A genuine terminal result or a current valid draw claim completes a game. No score-based favorable-draw adjudication is permitted. Seeds: corpus root 271828; per-pair recurrence is stored by `training/corpus.py`. Openings use 16 to 32 random legal plies. Only the next twelve plies allow seeded near-best move sampling within 30 cp, with probability 1/4. Record teacher score separately from actual move choice.

Pilot: 200 pairs took 19.3 seconds with four workers, producing 400 completed games, 28534 raw samples and 16998 distinct usable identities. Linear extrapolation is approximately 5.4 hours at the same load; it is an estimate, not a measured full runtime. Ceiling: 8 hours wall time for generation and 40 GiB on disk. Full data requirements remain at least 100000 completed games and 10000000 distinct reachable training positions. If the ceiling ends before both requirements pass, the full data gate is incomplete. Validation/test positions do not satisfy the training-position minimum.

Every game is independently replayed. Split by game lineage and an opening-family hash of the first eight plies. All positions from a lineage receive the same split. Cross-split canonical transpositions are quarantined from every split. Deduplicate within splits without counting later epochs as new positions. Report phase, material, ply, clock, teacher and outcome distributions, unfinished games and duplicate counts.

## Predeclared questions

1. Does trained neural evaluation improve held-out outcome/teacher loss against the same randomly initialized architecture? Three seeds, identical data and optimizer budget. Test groups stay unopened during model selection.
2. Does the validation-selected seed improve strength by at least 50 Elo against the unchanged classical evaluator, with the 95% lower bound above zero? At least 4000 games in color-reversed opening pairs, equal time, fixed source, threads and hash.
3. Does that contribution remain when node budgets are equal? A separate paired comparison isolates evaluator information from throughput.
4. Which transformer width among 32, 64 and 128 is useful? Diagnostic training and throughput pilots precede a new frozen architecture choice. The current 64-wide format is provisional. No inactive parameters count as an architecture improvement.
5. Does null-move pruning improve both short and longer time controls, and where does it fail in low-material zugzwang studies? Keep the negative cases and compare the off switch.
6. Do late-move reductions and futility improve strength under fixed time, and do they preserve the fixed tactical suite? Each has an individual off switch and raw regressions.
7. Does 1/2/4/8-thread root splitting improve strength or only total node count? Record depth, useful nodes, memory and stop latency at fixed wall time. No assumed linear scaling.
8. Does quantized-aware training reduce float/integer error enough to retain match strength? Scalar and SIMD integer outputs must be identical. Compare a frozen independent 100000-probe set and equal-budget matches.
9. Negative-result investigation: do very small diagnostic networks fail against the classical evaluator despite lower validation loss? Retain the loss improvement and any strength loss as separate findings.

## Learning budgets and selection

Candidate full training seeds are 17, 41 and 73, random initialization, CPU, two intra-op threads, AdamW, learning rate 0.001, batch 2048, 20000 updates, cosine decay to 5% of starting rate. Target is 0.5 outcome plus 0.5 sigmoid(original teacher cp / 400), from side-to-move perspective. Float training precedes quantized-aware training at the halfway point. Save optimizer, scheduler, sampler, CPU/device RNG and exact configuration atomically. Checkpoint every 250 updates. Select the seed and checkpoint by validation loss only, with no test access. Failed seeds remain failures. A different architecture or budget requires a new campaign version.

## Matches and uncertainty

Use pinned opponent executables/settings and immutable opening manifests. Each opening is played with colors reversed. Candidate classical comparison: 2000 pairs minimum. External comparison: 1000 pairs minimum against at least three pinned opponents/settings spanning weaker and stronger play. Publish losses caused by time, crash or illegal move. Resume at the pair identity; do not discard completed losing games.

Fixed-sample paired inference is the primary analysis. The independent unit is an opening pair, with score in [0,1] averaged over both games. Report the observed mean, a predeclared 95% paired-bootstrap interval with 20000 resamples and seed 104729, and the monotone logistic Elo transform `400 log10(p/(1-p))`. Endpoint intervals produce unbounded rating limits. An unfinished sample is inconclusive. No SPRT is enabled by default. Opponent relative Elo does not establish an absolute FIDE or CCRL rating.

Match time controls and final width must be frozen after speed pilots in a subsequent protocol version before decisive runs. This v1 does not authorize relabeling a diagnostic match as a full result. Full match gates cannot pass while those settings are unfrozen.

## Numerical and systems endpoints

Network arithmetic follows `docs/notes/quantization.md`. Diagnostic untrained maximum float/integer error was 46.1 cp. That observation does not freeze a trained-network tolerance. A justified trained-model tolerance must precede its held-out acceptance run. Record p50/p95/p99 command latency, evaluator ns/call, nodes/s, TT bytes, depth and cancellation for scalar and native kernels. UCI stop p99 must be below 50 ms under supported load. Race-instrumented execution is required separately from locking design review.

Independent verification must reject rehashed illegal PVs, swapped colors/results, wrong network outputs and invalid draw claims, plus missing artifacts, source mismatch and corrupt bytes. No saved pass boolean can substitute for these subprocess checks.

## Later version

[Prospective protocol v2](EXPERIMENT_PLAN_V2.md) records the unenforced v1 resource ceiling and freezes the screened-input, q1024, width, mixture and match settings for future full runs. Earlier diagnostics retain their original identities and limitations.
