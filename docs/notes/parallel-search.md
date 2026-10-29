# Work ownership and parallel root search

`Search::run` in `src/search.cpp` owns a finite root list for each depth. An atomic index assigns roots to at most eight worker objects. Each worker owns killers, counter moves, history values, statistics and its neural accumulator. The root position is copied before local search. Only cancellation, node tickets, a shared root alpha and the locked transposition table are shared.

With one principal variation, roots that cannot beat shared alpha are screened with a unit window. A root that improves alpha is resolved to an exact score. Completed fail-low roots retain upper-bound labels. Sorting prefers exact results on tied scores. With several principal variations, all roots are resolved at full width so displayed scores have the claimed meaning. Interrupted iterations retain the previous completed depth instead of publishing a mixture of bounds as exact MultiPV results.

This design avoids unsynchronized table reads and establishes real shared work, but roots differ sharply in cost. Thread creation at each depth, table mutex contention and searching early roots before alpha improves can all waste work. Total node count is not useful parallel speedup. The start-position depth-six diagnostic dropped from 82458 to 13037 nodes after root screening while retaining its score. That is a fixed example, not a scaling or strength estimate. The full 1/2/4/8-thread profiles and race campaign are still required.

## Final-source evidence update, October 28

The [partial thread evidence join](../../results/final-thread-evidence-2026-10-28/README.md) checks both existing exact5803-source TSan archives, including all22native cases, actual compile flags, program hashes and complete logs. It joins the accepted saved1ff/52d performance sample and five thread comparisons without rerunning them. The interrupted older tactical-race replay remains failed.

For the neural-blend performance mode, useful-work ratios at2/4/8threads were approximately1.68/2.28/2.79 versus one thread in that250ms diagnostic workload. These are observed search-work ratios, not linear scaling guarantees or Elo. Full measurements and memory observations are retained in the original performance proof.

The accepted G04 stop percentile used small hash tables with neural evaluation disabled. It cannot supply the missing16MiB/neural10/52d/lazy/cache/tactical timing result. The [new runtime prerequisite](../../results/final-thread-runtime-preflight-2026-10-28/README.md) confirms one eight-thread128-node-budget neural search with a newly qualified local sanitizer runtime, after a preserved optional-logging setup failure. It is not a race campaign. The [proposed exact-configuration workload](../../config/thread-runtime-v1.proposed.json) still requires implementation, independent checking and a fresh finite admission before execution. No match schedule is restarted.
