# Selectivity and zugzwang risk

`src/search.cpp` exposes individual switches for null move, reductions, extensions, futility, PVS, aspiration, history, SEE and table use. The nonselective configuration is checked against a separate exhaustive minimax in `tests/search_test.cpp`. Selective speedups are hypotheses requiring matches, rather than consequences of a green correctness test.

Null move is disabled in check, near the rule-clock boundary, without nonpawn material, and after a null move. Deeper fail-highs receive a verification search. These safeguards reduce common pawn-ending zugzwang errors but do not prove every rook or minor-piece ending safe. Synthetic null histories are separated from real game histories, and game draw claims are suppressed in synthetic subtrees. An early version lacked that explicit distinction; the corrected rule test prevents recurrence.

Late-move reductions apply to sufficiently late quiet moves outside check and checking replies; an improving reduced result is searched again at full depth. Check extensions are bounded by ply. Futility requires a quiet nonpromoting move, a narrow window, a shallow depth and an already searched alternative; it cannot skip a checking move. Quiescence searches all evasions in check and includes promotions, with a finite depth ceiling. The ceiling is an approximation, not an exact tactical proof.

The full study suite and short/long time-control ablations remain necessary. No pruning feature is claimed to improve Elo until its matched results exist. A failed zugzwang or tactical case must be kept as a regression, even if aggregate node speed improves.
