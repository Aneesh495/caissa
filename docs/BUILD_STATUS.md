# Build status

Status: foundational increment. Full acceptance is unverified. No release.

Executed: host and account inspection; intended repository name was available. The initial source provides a C++23 build and a version command only.

Pending: rule core, independent legality checks, search, UCI, original learning, arena, analysis interface, recovery, source-bound semantic verification and full campaigns.

Resource audit: 8 logical CPU cores, 16 GiB RAM, approximately 115 GiB free at initialization. GPU training capability and campaign throughput are not yet measured.

Rules increment: typed moves, independent ray-table stepping, structural FEN validation, bitboard legal generation, standard/Chess960 castling, exact undo, repetition and search identities. Executed `make test`: start perft through depth 4 (197281), Kiwipete through depth 3 (97862), illegal en passant and Chess960 overlap tests, 5000 seeded restoration samples. These are initial checks, not the full rules gate.
