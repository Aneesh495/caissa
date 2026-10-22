# Domain contract

Square indices use a1=0, h1=7, a8=56. White is color zero. A position owns piece placement, side, rook-origin castling rights, en passant target, halfmove and fullmove counters, and the reversible history available to its caller. A bare FEN cannot establish earlier repetitions or prove historical reachability.

Moves carry source, target, promotion and a semantic flag. Internally castling identifies the participating rook, making overlap cases explicit. UCI standard and Chess960 move encodings are protocol views of the same move.

Scores are integer centipawns from the side-to-move perspective. Mate scores encode distance in plies. Search identities must include history and rule-clock context before a table cutoff is permitted. A board repetition key alone cannot certify a reusable search score.

Rule correctness precedes corpus generation. Diagnostic checks do not certify learning or strength. Full acceptance must retain failed and unexecuted gates. Public results must identify executable source, input bytes, model, hardware, budgets, adjudication, and independent replay.

The default executable must run without Python, network access, tablebases or another chess engine. Model absence must be explicit; a classical evaluator is an available baseline, not a substitute for a trained network claim.
