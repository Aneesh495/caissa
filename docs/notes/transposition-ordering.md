# Move hints across reversible histories

A search score belongs to a board, rule clock and reversible history. A legal move suggestion belongs to the board. These have different reuse rules.

`Position::search_key` includes the reversible sequence and synthetic null context. `TranspositionTable::probe` requires that complete key before returning a bound. This deliberately loses some conventional transposition hits. Removing the history from that key would make repetition-dependent scores unsafe.

The separate ordering table stores only a full board key, move, depth and age. It has no score, evaluation or bound field. Search verifies the suggested move against the current legal list before ordering it first. A hint can change the traversal and therefore the outcome of selective or interrupted search. It cannot produce a transposition cutoff directly. `Ordering Hints=false` removes this mechanism for matched experiments.

Both tables share striped mutex ownership. No lock spans recursive search. The main table receives at most seven eighths of the configured byte budget before rounding to a power of two; hints use the remaining budget. `bytes()` includes both arrays. Replacement prefers a fresh search generation or a deeper suggestion. Full tags reject index collisions.

The native table test checks full tags, memory bounds, separation from score entries, concurrent readers/writers and clearing. The independent minimax search test still checks exhaustive values with selective heuristics disabled. Playing strength is a separate paired experiment. The initial pilot compares the same frozen executable with only the hint option changed, one thread, 16 MiB and 20 ms per move. Its results must be retained even if negative.

Sources: [table contract](../../include/caissa/table.hpp), [table implementation](../../src/table.cpp), [search](../../src/search.cpp), [checks](../../tests/table_test.cpp).
