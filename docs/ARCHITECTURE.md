# Architecture

The native executable owns rules, legal moves, search, notation and neural inference. Python handles original selfplay orchestration, training, matches and independent artifact verification. TypeScript owns the loopback analysis service and browser board. The native core runs without Python, network access, tablebases or another engine.

| Boundary | Source | Contract |
|---|---|---|
| Geometry | `src/attacks.cpp` | a1=0 bitboards, generated rays, nearest blockers |
| Position | `src/position.cpp`, `src/movegen.cpp` | owned state, rook-origin rights, exact undo |
| Rules | `src/rules.cpp` | mate precedence, claims distinct from automatic termination |
| Notation | `src/notation.cpp` | bounded SAN/PGN, explicit variation parentage |
| Evaluation | `src/evaluation.cpp`, `src/network.cpp` | side-to-move cp, mate range reserved |
| Search | `src/search.cpp`, `src/table.cpp` | worker-local heuristics, locked table, shared root alpha |
| Protocol | `src/uci.cpp` | one search owner, bounded input, joined teardown |
| Learning | `training/` | original labels, lineage splits, transactional checkpoints |
| Strength | `arena/` | paired colors, all failures retained, opening-cluster uncertainty |
| Verification | `verification/` | trusted source, independent inference/replay/statistics |
| Analysis | `analysis-service/`, `web/` | request generations, budgets, cancellation and backpressure |

Editable diagrams and rendered SVGs:

- [System context](diagrams/system-context.svg), [source](diagrams/system-context.dot)
- [Components](diagrams/components.svg), [source](diagrams/components.dot)
- [Legality](diagrams/legality.svg), [source](diagrams/legality.dot)
- [Make/unmake](diagrams/undo.svg), [source](diagrams/undo.dot)
- [Search recursion](diagrams/search-recursion.svg), [source](diagrams/search-recursion.dot)
- [Table ownership](diagrams/tt-ownership.svg), [source](diagrams/tt-ownership.dot)
- [Neural refresh](diagrams/nnue-refresh.svg), [source](diagrams/nnue-refresh.dot)
- [Training lineage](diagrams/training-lineage.svg), [source](diagrams/training-lineage.dot)
- [UCI lifecycle](diagrams/uci-lifecycle.svg), [source](diagrams/uci-lifecycle.dot)
- [Paired arena](diagrams/arena-pairs.svg), [source](diagrams/arena-pairs.dot)
- [Evidence lineage](diagrams/evidence-lineage.svg), [source](diagrams/evidence-lineage.dot)
- [Recovery](diagrams/failure-recovery.svg), [source](diagrams/failure-recovery.dot)
- [Local deployment](diagrams/local-deployment.svg), [source](diagrams/local-deployment.dot)
- [Independent testing](diagrams/correctness-testing.svg), [source](diagrams/correctness-testing.dot)
