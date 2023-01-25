# Restoration replay

G02 requires one million seeded make/unmake pairs. The native state transport
exposes the actual board, color/piece bitboards, castling rook identities,
clocks, en passant, position/repetition/search keys, complete repetition
history, synthetic null depth and both deferred neural vectors. It also emits
the classical score and scalar/native/full-refresh neural evaluations.

`caissa --state-probe NETWORK` accepts bounded newline-delimited `reset FEN`,
`reset 960|FEN`, `move UCI`, `null`, `undo` and `state` commands. The transport
is separate from UCI and is not exposed by the HTTP service. Invalid commands
return a structured error. Requests are capped at 1024 bytes, replies at 16384
bytes, the stack at 127 pushes and the process at ten million commands.

The [frozen profile](../config/restoration-v1.json) retains the selected
q4096 network, float checkpoint, ten-percent mixture and classical contract1.
It defines a deterministic walk with twelve fixture families, including
overlapping Chess960 castling, both promotion paths, en passant, king-bucket
reentry, threefold cycles and boundary clocks. Nested null branches are extra
observations. Each ordinary trial makes a move, observes the child, unmakes
and observes the parent, then commits the move to continue a reachable walk.

[The independent state oracle](../verification/restoration_state.py) evolves
its own python-chess board and game history. It reconstructs every native
identity from the hash contract, computes sparse sums from the saved network
bytes, independently evaluates the original classical formula and applies
the integer dense layers and blend. It does not import the producer, native
search or training code. [The replay driver](../verification/restoration.py)
also reexecutes every request through a copied, externally pinned native
program. Complete saved states and reply-byte hashes must match that fresh
execution. Every restored parent equals the previously reconstructed state.

The full entry driver is `restoration-v1` on G02. Its `restoration` object has
distinct declared artifact references `profile`, `config`, `summary` and
`observations`. Source, runtime and evaluator identities must match the full
deployment. Replays write outside the original bundle. A diagnostic prefix or
a forged saved success flag cannot satisfy the million-pair sample.

The initial development prefix passed 512 pairs and all twenty native cases.
The expanded1280-pair controls found an actual verifier defect: Python's
boolean/integer equality allowed a saved pawn value `true` to equal `1`.
Validating only the fresh native object's types did not validate the saved
wire object. The corrected boundary checks every saved field and nested array
type before oracle reconstruction. The original accepted mutant, failure
logs and actual exit0 remain retained. The same mutant then produced exit1.
Linux/macOS CI40193438634 passed the positive prefix and eleven controls.

The controls rehash modified raw observations after changing a clock, rights,
history, accumulator, piece type, score, sequence index and declared sample.
They also reject an undersized full entry and writing inside the evidence.
These prefixes are development evidence, not a full G02 pass.

[The full owner](../tools/restoration_campaign.py) uses only
`runs/restoration-full-v1`. One persistent scope retains a two-hour wall/active
ceiling, the original project deadline, a16GiB additional-disk ceiling,10GiB
reserve and at most three meaningful attempts. Native and model bytes are
pinned before observation; compiled native inputs must match their declared
committed source. Source is archived before either child phase. Reuse of
complete raw observations on a bounded retry cannot alter their identities.
Every failed attempt stays recorded and a completed scope cannot restart.
The producer is capped at1800seconds and independent replay at3600seconds
inside that unchanged cumulative scope. No data, learning, numerical or
strength scope is reopened.

G02 verifies state restoration and the selected evaluator's exact behavior.
It does not establish neural playing strength, finish other gates or produce
an absolute Elo estimate.

The [full development sample](../results/restoration-full-2026-10-25/README.md)
completed1000000 pairs,1040911 independent full-state reconstructions and
3040911 fresh native requests for the archived abbe/636 actor. The actual
producer and independent stages used296.80 and663.94seconds. The original
7200-second scope closed after961.17seconds and one attempt. Exact saved
program/model and receipts are portable; the5.349GB raw journal is retained
locally and separately indexed, with bulk distribution still pending.
Later native commands create different program identities and need explicit
final deployment binding. This observation does not turn other gates green.
