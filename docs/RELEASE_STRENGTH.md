# Caissa v0.1.0 playing strength

On November 6, 2026, the default classical engine played 192 games against
Stockfish 19. An independent verifier replayed every game, checked the
recorded moves and principal variations, and recomputed the score and
intervals from the raw paired records.

| Opponent | Caissa W-D-L | Score | Relative Elo | 95% interval |
|---|---:|---:|---:|---:|
| Stockfish 19, unrestricted | 15-1-80 | 16.15% | −286 | [−394, −206] |
| Stockfish 19, Skill Level 0 | 93-0-3 | 96.88% | +597 | [+442, unbounded] |

Both estimates describe this engine matchup under the conditions below.
Skill Level is a move-selection setting, and the comparisons have no
calibration to a human or rating-list Elo scale. See the [Stockfish rating
FAQ](https://official-stockfish.github.io/docs/stockfish-wiki/Stockfish-FAQ.html#the-elo-rating-of-stockfish).

## Conditions

- Apple M2 arm64, 8 logical cores, 16 GiB memory, macOS 26.7.2.
- Four concurrent games, with one thread, 32 MiB hash, one principal variation
  and pondering disabled for both engines. Standard chess, no tablebases,
  classical Caissa, and `UCI_LimitStrength=false` for both Stockfish settings.
  `Skill Level` was 20 for unrestricted play and 0 for the weakened opponent.
  Each fresh process warmed up at 1,000 nodes.
- `go movetime 50` for each search, with a 100 ms transport allowance before
  scoring a time loss. This is a per-move budget. The first 48 distinct opening
  families in the [frozen opening file](../config/strength-openings.json) were
  used in both settings, with two color-reversed games per opening. These
  openings were also used in earlier research.
- The arena played to checkmate, another rules termination, or a forfeit.
  It claimed draws at threefold repetition or 100 halfmoves. The 1,024-ply
  safety limit was reached by zero games. There were zero crashes, protocol
  failures or illegal moves.
- The 95% intervals are percentile bootstrap intervals using 20,000 resamples
  of the 48 opening pairs per opponent, with both colors kept together. Match
  score is wins plus half of draws, divided by games. Elo transforms that score
  using 400 × log10(score / (1 − score)). The Skill Level 0 upper endpoint
  remains unbounded because its 97.5th percentile score reached 100%.

Unrestricted Stockfish forfeited on time in four games. The primary result
counts those games as Caissa wins. As a sensitivity check, scoring all four
as Caissa losses gives 11 wins, 1 draw and 84 losses, or **−346 relative Elo
with a 95% interval of [−470, −261]**. This is a hypothetical recoding of
those outcomes, separate from the observed result.

## Source and replay

The rated engine was built from
[`ff3d88d`](https://github.com/Aneesh495/caissa/commit/ff3d88de808f04f51dd945d02ed62559a909b737)
using Apple clang 21, Release and LTO. The macOS and Linux distributions were
built separately from the same engine and analysis-board source, with their own
toolchains. See the [distribution build and smoke tests](https://github.com/Aneesh495/caissa/actions/runs/42302067833).

The [release assets](https://github.com/Aneesh495/caissa/releases/tag/v0.1.0)
include `caissa-0.1.0-strength.tar.gz` with both PGNs, raw per-move UCI
observations, pair records, opening data, configurations, manifests and the
exact rated executable. Local checkout path prefixes were removed from the
configuration and build log. The matched Stockfish 19 was the Homebrew macOS
arm64 build. Its executable hash is in `ENVIRONMENT.txt` and the protocol
receipts. Stockfish is distributed separately under the [GPL](https://stockfishchess.org/about/).

Extract the strength archive in a Caissa source checkout. With Python 3.12
and the archive's `DEPENDENCIES.txt` installed, run:

```sh
evidence=caissa-0.1.0-strength
engine_sha=$(shasum -a 256 "$evidence/bin/caissa" | cut -d ' ' -f1)
for setting in full skill0; do
  python -m verification.strength "$evidence/$setting" \
    --openings "$evidence/strength-openings.json" --engine-sha256 "$engine_sha"
done
```

The expected engine SHA-256 is
`6c9311e37be0dd822444043d7cc83ed0ca86e497d23074b6dcbd7786c6cd3970`.
Replay checks the recorded games and recomputes the statistics. It requires
neither engine to run.
