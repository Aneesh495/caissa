# Independent search semantics

An actual pre-repair search returned-552cp for a losing king at clock99 even
though an intended legal move permits a draw claim. The original program and
raw response remain retained. The same search is shared by neural and classical
actors; the correction changes no evaluator, learning data or old match receipt.

A claimable real child lets both players force a draw: the previous mover can
announce that move and the current player can claim afterward. Synthetic null
branches suppress these claims. The root can still choose a winning reset or
mate. Optional intended claims also create a zero floor at search frontiers.
A reversible-history parity screen avoids generating continuations when the
next side has no repeated predecessor and the clock is below99. Thirty-five
native search cases cover the losing clock/repetition witnesses, frontier
claims, capture resets and immediate mate.

`caissa --search-probe` exposes the original `Search` and `TranspositionTable`
through a separate bounded diagnostic channel. It has no neural model or
alternate search. `search DEPTH FLAGS SEED NODES CHESS960|FEN|MOVES` uses a
single worker and emits the actual score, move, PV, completion and work
counters. Bits0..12 control table, PVS, aspiration, hints, LMR, null move,
quiescence, extensions, history, SEE, futility, evaluation cache and tactical
generation. Depth is bounded to6 and nodes to500000. Table commands are
`clear`, `new`, `store KEY FROM TO SCORE EVAL DEPTH BOUND PLY end`,
`probe KEY PLY` and `hint KEY FROM TO DEPTH`; keys are sixteen hexadecimal
digits. They read and write the real table. Requests/replies are bounded to
1024/16384bytes, histories to64moves and a process to10000commands.

[The prospective profile](../config/search-semantics-v1.json) fixes17 positions,
eight exact option masks, two tie seeds,96 table trials, the LMR window witness
and thirteen switch-off ablations across eight positions. Each ablation keeps
the other switches fixed. Native queries have100000 nodes each. The producer
has240seconds, independent replay600seconds, raw output16MiB, a5000-command
ceiling and a cumulative one-million-node exhaustive-oracle ceiling.

[The independent oracle](../verification/search_semantics.py) uses python-chess
and the separately authored classical contract1 evaluator. It enumerates full
trees with optional current/intended draw choices, checks exact search scores
and optimal root moves, and preserves all per-move oracle values. Separate
table reconstruction checks exact/lower/upper labels, full-key identity,
positive/negative mate normalization across plies, replacement protection,
score-free hints and clearing. Every saved request and reply is replayed
through the exact copied native program. No native producer/search/training
module supplies expected values.

Selective ablations record actual counters and differences from exhaustive
values. They do not require an approximate heuristic to equal exhaustive
search, hide its disagreements or establish playing strength. The LMR regression
specifically requires agreement and actual reduction/research work. The full
G05 adapter is `search-semantics-v1`, with distinct declared `search_semantics`
references `profile`, `config`, `summary` and `observations`. It requires all
fixed work, source/runtime identity and external replay output. Completing G05
alone leaves the other fifteen semantic domains incomplete.
