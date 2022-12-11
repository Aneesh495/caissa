# Deferred neural state

The search previously saved, updated and restored both neural accumulator
vectors around every move. A transposition cutoff, terminal position, futility
skip or evaluation-cache hit could make those updates unnecessary.

`Lazy Neural` is an experimental UCI option, initially false. It changes only
when the sparse transformer runs. The loaded weights, dense arithmetic,
classical contract, blending percentage, move ordering and search decisions
remain the same. Each worker owns a bounded stack with 128 frames and a fixed
network reference. Zero-weight searches do not allocate that stack.

A pushed frame records the position key, both king buckets and the at most four
unique squares changed by `Position::make`. This covers captures, en passant,
promotion and overlapping Chess960 castling. A null move records no piece
changes. Returning from a move pops a frame instead of copying its parent's
vectors back.

On an actual neural evaluation, each perspective starts from the nearest
materialized ancestor in its final king bucket. Piece changes between that
ancestor and the current frame are applied with that bucket's embedding rows.
They telescope exactly, including a king that left and returned to its bucket
between observations. With no matching ancestor, that perspective is rebuilt
from the current board. Sparse sums are never clipped on this path. Activation
clipping and dense rounding still occur in the established evaluator.

The eager option uses the established `Network::update` implementation on
every push. It provides an in-process reference. The new stack also removes
the eager restore copy, so a performance study must retain a third arm using
the archived executable to distinguish that change from deferred updates.

Search statistics expose pushes, materializations, perspective copies,
perspective refreshes and changed-square applications. Counters accumulate
over root moves and iterative-deepening iterations. Initial root fallback
evaluation is outside these worker counters. Materializations count frames
whose values are computed, including frames reset eagerly.

The native test compares deferred vectors with complete board refreshes and
the established eager updater through a seeded branching tree. Separate
fixtures cover king-bucket reentry, unobserved roots, null moves, all relevant
special moves, stale ownership and capacity. Fixed-node searches compare
scores, complete principal variations, root bounds, node counts and search
counters with weights 0, 10 and 100, cache on/off and neural bounds on/off.
Parallel tests require legal PVs rather than deterministic thread scheduling.

This engineering change has no measured Elo result. The original full neural
comparison remains failed. Its candidate, games and model identities stay
unchanged while this implementation is developed. The selected full model
remains seed 73, step 2750. No test-result checkpoint selection, retraining,
new mixture or classical-contract change is part of this optimization.
