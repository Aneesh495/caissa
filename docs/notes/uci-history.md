# Validated position-prefix reuse

UCI clients send the complete game history with each search. `PositionLine` in
`src/position_line.cpp` keeps the validated root, move strings and exact undo
records. With an identical root FEN and Chess960 mode, an update reuses the common
prefix, unmakes a divergent suffix and validates every new move. Changing any
root field starts fresh. Its public position view is const.

An update produces a complete new value. `src/uci.cpp` installs it only after all
input has validated and the preceding search has joined. Illegal suffixes or
roots leave the installed board, repetition history and clocks intact. A shorter
command rewinds actual undo records instead of reconstructing a bare FEN, which
would lose repetition history. The existing 1024-ply ceiling still applies.

`tests/position_line_test.cpp` independently replays moves using mailbox legality.
It checked 1000 divergent and 1000 repeated updates, en passant, ordinary and
overlapping Chess960 castling roots, malformed input and 1024 reversible plies.
Every board/hash/history/draw comparison passed. A truncation from 1024 to eight
plies restored the threefold claim and removed the later automatic-draw history.
Seventy actual UCI fixed-node searches matched the preceding executable, including
Chess960, claim/automatic repetition and clock boundaries. Thirteen native tests
also passed under ASan/UBSan.

An actual 10000-sequence protocol run passed independent replay and six semantic
controls. Stop p99 was 31.192791 ms and maximum was 410.408750 ms under concurrent
data work. These are development observations, not final release evidence or a
claim that every stop meets the percentile threshold.

The paired transport study sent 130 real position/readiness exchanges and checked
every returned FEN with python-chess. Median latencies in milliseconds were:

| History plies | Previous parser | Prefix reuse |
|---|---:|---:|
| 0 | 0.3545 | 0.0880 |
| 8 | 0.1437 | 0.1249 |
| 32 | 0.2819 | 0.1136 |
| 128 | 0.5393 | 0.2061 |
| 256 | 0.3333 | 0.2600 |
| 512 | 1.5630 | 1.7800 |
| 1024 | 2.2325 | 0.9271 |

The host was contended and one history size regressed. Ordinary histories were
already below a millisecond. This smaller optimization does not explain or fix
the earlier timed resource pilot's long scheduling tails and establishes no Elo
gain. Controlled host load remains necessary for decisive timed matches.
