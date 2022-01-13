# Position identity and history

`Position::key` in `src/position.cpp` hashes exact piece placement, turn, rook-origin rights and the literal en passant marker. It excludes clocks. `repetition_key` removes the marker when every en passant capture is illegal, including discovered checks. FIDE position identity requires the same available moves, rather than textual FEN equality.

`search_key` additionally folds the halfmove clock and known reversible history in order. This conservative choice sacrifices some table hits to avoid importing a draw from another path. A hash collision remains possible as for any finite key; full 64-bit tags are checked before a table entry can be used. Two reversible move paths can therefore have the same repetition key and different search keys.

`src/rules.cpp` distinguishes a current threefold or 100-ply claim from automatic fivefold and 150-ply termination. `claim_by_move` checks the intended move. Checkmate is resolved before automatic draw clocks. Search can treat a claim as a zero-valued available action while retaining a possible win. It must never turn a claim into a universal board-only draw score.

Dead-position recognition is deliberately conservative: bare kings, one minor total, or bishop-only material confined to a single color complex. Two knights are not declared dead. General fortress recognition is not implemented. A FEN cannot recover earlier repetitions, confirm promotion provenance, or establish every historical reachability condition.

`tests/rules_test.cpp` exercises clock boundaries, mate precedence, repetition reconstructed from moves, the same board parsed without history, and illegal en passant markers. `tests/position_test.cpp` checks reversible state. `tools/differential.py` compared 100000 reachable positions with chess 1.11.2 and the separately implemented 10x12 mailbox generator in `src/reference.cpp`. Initial run: zero mismatches, 96589 unique board identities. That diagnostic covers neither all legal positions nor a complete campaign frozen to a release source.
