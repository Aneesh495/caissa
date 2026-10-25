# Deferred neural state

The selected ten-percent neural mixture with evaluation caching took less
wall time on both measured hosts. All three implementations returned identical
fixed-node search output. No new strength games were played by this study.

The development source is `113c5dbee14fd0b4262ed30e7b256c8e36afee9b`.
[Hosted run 40179372115](https://github.com/Aneesh495/caissa/actions/runs/40179372115)
passed on Linux x86-64 and macOS arm64. The original
[profile](../../config/deferred-neural-v1.json) is immutable. One execution per
platform used 554.43 and 447.88 seconds within the original 1800-second job,
5400-second cumulative and three-hour wall ceilings. The scope is closed;
ordinary pushes and manual requests cannot restart it.

## Correctness

Each platform passed nineteen native cases in Release, ASan/UBSan and TSan.
Each mode also replayed one million seeded tree operations with the unchanged
selected model. Deferred vectors matched eager updates and complete board
refreshes at all 142769 materialization observations, plus the explicit corner
fixtures. The walk is repeated across modes, not three million distinct
positions. This deferred-observation test is not the final G02 campaign.

Every mode compared 144 eager/deferred search pairs at fixed nodes, including
weights 0/10/100, cache and certified-bound settings, special moves, full PVs,
root bounds and tree counters. Separate 2/4/8-worker searches returned legal
PVs. Stale ownership, maximum depth, unobserved roots, null moves and a king
leaving and returning to its bucket were exercised.

The network remains
`52d0306143392ad683c3ebb09fe013f34e1f9e2bc44d3aa153b32314207374b7`,
exported from the original validation-selected checkpoint
`c76d8e9ef0f2255531bc9085f5d0330a7a4152cf9b21a65ff8aee740ab8b2005`.
No float weights, selected checkpoint, mixture or classical contract changed.

## Runtime observations

Each host made 720 requests, grouped into 240 randomized triplets across eight
positions, five repetitions, three weights and cache on/off. Every arm received
the same 20000-node ceiling, one thread, 16 MiB hash, tactical generation and a
one-node warmup. Some solved positions finished before the node ceiling. Each
triplet compared the archived executable, the new eager stack and deferred
stack. Scores, best moves, full iteration output, PVs and search counters agreed.

The table shows median paired wall-time ratios. Below one favors deferral.

| Weight | Cache | Linux/archive | macOS/archive | Linux/stack eager | macOS/stack eager |
|---|---|---|---|---|---|
| 0 | off | 0.7902 | 0.8387 | 0.9963 | 0.9893 |
| 0 | on | 0.7986 | 0.8707 | 1.0077 | 1.0637 |
| 10 | off | 0.9614 | 0.9952 | 0.9902 | 0.9785 |
| 10 | on | 0.9107 | 0.9297 | 0.9486 | 0.9625 |
| 100 | off | 0.9486 | 0.9828 | 0.9724 | 1.0164 |
| 100 | on | 0.8839 | 0.9412 | 0.9247 | 0.9424 |

At the deployed ten-percent mixture with caching, deferral reduced median
wall time by 8.93% on Linux and 7.03% on macOS relative to the archived code.
Against the new eager stack, the reductions were 5.14% and 3.75%. The eager
stack already removes the old restore copy, so that benefit must be separated.
Several other comparisons were neutral or slower. Zero weight loads a network
but skips its contribution; it is not a measurement of default classical mode.

In the selected cached group, both platforms recorded 780620 pushes. Computed
frames fell from 791580 to 294325, perspective copies from 1561240 to 270130,
and changed-square applications from 2692590 to 635040. Perspective rebuilds
increased from 231605 to 318520. Skipping updates can lose an unobserved
ancestor's reusable state, so fewer materializations do not imply uniformly
lower cost.

These are host-specific wall observations. They do not estimate Elo or prove
the runtime cost was the sole cause of the original neural strength loss.
Classical remains the default and `Lazy Neural` remains experimental/off.

## Independent reconstruction and failures

The [independent checker](../../verification/deferred_neural.py) imports no
producer, arena, training or search implementation. It reconstructs all 1440
native query records, randomized ordering, legal PVs, exact triplets, timing
ratios, model/options and work sums from raw transport lines. It does not
execute a native program or create a new timing observation. Eight rehashed
controls reject partial samples, repeated counters, illegal PVs, forged
timestamps, reordered arms, changed mixtures, substituted models and false
runtime summaries. Actual exit receipts are retained.

The first ordinary CI passed the nineteen native cases but failed service
integration because strict telemetry did not yet include the new counters.
Both original failure logs are saved. Source `651e5c9` fixed the complete typed
transport and browser labels; CI 40179153228 passed. CI 40179372109 also passed
at the frozen diagnostic source. These failures were not overwritten.

Each platform's `RAW.zip` contains complete runtime observations, configuration,
campaign stage receipts/logs and the exact Release and instrumented saved
programs. `MANIFEST.json` records external archive and executable identities.
Build object files are omitted from the portable artifacts. The previously
failed original numerical and 4000-game neural studies remain failed. This
development result does not satisfy missing full gates or justify release.
