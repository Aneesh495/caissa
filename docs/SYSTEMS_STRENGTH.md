# Search-system comparisons

`verification.systems_strength` admits prospective parallel and heuristic
comparison contracts separately from the neural contribution experiment.
No production systems profile or game sample is frozen by this implementation.
A bounded source-archiving owner is still required before games may start.

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
