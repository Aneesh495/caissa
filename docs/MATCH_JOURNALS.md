# Pair, game and PGN agreement

The arena stores every trajectory in a paired record, a separate per-game
JSON journal and a PGN. Mathematical replay of the paired record alone does
not prove that the exported files describe the same games.

[The independent reader](../verification/match_journals.py) requires the exact
pair/game/PGN file inventory, strict JSON types and reversed-color identities.
Each separate game must equal its paired record. Independent board replay
checks legal moves, terminal/draw provenance, forfeits, actual budget/history
requests, request timings and every recorded PV. The parsed PGN must contain
the same initial position, colors, result, termination, opening and complete
played sequence, with no extra game or unrecorded variation. Unavailable EP
targets are normalized according to PGN/FEN's legal-EP convention.

The reader is bounded to2000 pairs per campaign,64MiB per JSON record,4MiB per
PGN and an externally chosen wall/active deadline of at most3600seconds.
It refuses a held decisive-match owner before reading game artifacts. It
does not run engines, train, infer a rating or certify a full strength sample.

[The hosted controls](../tests/match_journals.py) use the four games already
created by the real native CI arena. They rehash mutations of split records,
PGN results/colors/moves, boolean identities, an invented75-move draw, an
illegal PV, a missing PGN and an extra pair file. The intended outcome is one
positive reconstruction and nine semantic rejections. They are run remotely
while the local frozen v4 strength sequence owns the timed host. Their actual
results must be inspected before claiming this increment verified.

This strengthens the raw-artifact portion of G14/G15. It supplements the
fixed-sample strength verifier and does not replace any of its game counts,
unchanged-control requirements, statistics or gain endpoints.
