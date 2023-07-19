# Search-system comparisons

`verification.systems_strength` admits prospective parallel and heuristic
comparison contracts separately from the neural contribution experiment.
The prospective profiles are frozen in `config/systems-parallel-v1.json` and
`config/systems-heuristics-v1.json`. Their freeze proof is published in
`results/systems-strength-contract-2026-10-26`. Freezing these profiles does
not mean that their games have been collected.
`tools.systems_strength` owns the separately bounded experiments. Its actual
frozen profile, source archive and original learned inputs must be ready before
games may start. It refuses to steal the current strength sequence's handoff.

The parallel matrix contains six comparisons: 2, 4 and 8 threads against one
thread at 100 and 400 milliseconds per move, with 100 reversed-color pairs
each. Both actors use the same validation-selected neural mixture and saved
executable. Hash allocation stays at 16 MiB per actor. One comparison runs at
a time, so simultaneous matches do not oversubscribe the eight-core host.

The heuristic matrix contains forty comparisons. For each of ten search
switches, the fully enabled original classical search faces the same search
with that switch disabled. Equal-time budgets use 100 and 400 milliseconds
with 50 pairs each; equal-node budgets use 20,000 and 100,000 nodes with 25
pairs each. The complete matrices require 1,200 and 3,000 games respectively.
They do not select another model, change classical contract 1 or replace the
failed neural endpoint.

The owner snapshots committed source, verifies original model-selection
lineage, saves exact actor/profile/opening bytes and inherits its exclusive
host lease into independent readers. Resumption re-enters the saved source and
retains original wall/active/disk/attempt limits and all completed game bytes.
A closed domain cannot run again. A comparison with unfinished games stays
failed while other predeclared comparisons can still be collected.

Admission checks exact typed option inventories, identical executable/model
paths, selected network identity, held-out openings, actual configured UCI
commands and declared option ranges. Unknown or extra resource/actor options
cannot silently change the comparison. Parallel and heuristic domains retain
their separate eight-hour and twelve-hour wall/active caps, three attempts,
20 GiB additional disk and 10 GiB reserve inside the existing parent deadline.

One comparison's independent reader checks every paired record, separate game
journal and PGN, reconstructs legal moves, results, draw claims and principal
variations, and independently recomputes the fixed paired bootstrap. Unfinished
games remain failures. Negative effects and censored intervals remain results.
A comparison pass certifies neither the complete matrix nor the G10 performance,
memory, stop-latency and race-instrumentation requirements.

Hosted controls admit all 46 metadata settings and send rehashed altered
contracts through the actual reader CLI. Four real integration games cannot
be promoted into a full comparison by adding a plausible configuration.
