# Original selfplay and replay

`src/selfplay.cpp` creates legal random openings, then uses the original search and classical evaluator. Every saved sample separates the side-to-move search score from the eventual white-perspective result. Early near-best sampling is seeded and bounded to a 30 cp window. It supplies move diversity without asking another engine for labels. A game ending during the opening can legitimately have zero training samples. The corpus runner initially rejected that case; the correction retains the completed game and contributes zero positions.

`training/corpus.py` journals a complete color-reversed pair with an atomic file replacement and directory fsync. Existing pairs are not replayed during restart. Configuration and executable hashes must match. `training/prepare.py` uses python-chess only as an isolated legal replay oracle. It reconstructs every sample FEN, checks the actual terminal or current claim, and rejects swapped result colors. A 512-ply resource exhaustion stays unfinished, with no manufactured draw label.

The 400-game pilot produced 28534 samples and 16998 distinct usable identities. This is insufficient for full learning acceptance. The larger campaign uses a frozen older teacher executable, whose source identity is separate from later candidate improvements. Improving candidate search does not retroactively improve historical labels. The full distinct-training count must come from replay and deduplication, not from generated file counts or repeated epochs.

## Searched-policy pilot

The original 500-node, three-PV teacher often exhausted its budget before a complete root iteration. In the observed prefix, approximately 82% of teacher samples had completed depth zero. Such a sample is a legal position with a valid static fallback score, but its played move may be the legal fallback rather than a searched choice. These are retained and disclosed instead of being described as deep teacher labels.

The separate `searched-v2` policy uses one principal variation and a seeded root order. The seed is mixed with the board key through an explicit Fisher-Yates permutation before iterative deepening. Different reversed-game seeds diversify equal-score decisions and finite-budget traversals. Normal play uses seed zero and keeps its deterministic root order. This adds no external labels or network. A new 5000-node pilot records completed depths before any prospective full resource choice.

Corpus configuration, native command and each game's policy/budget must agree. Preparation and the independent data verifier reject a mismatch. The legacy teacher, journals and runtime identities are immutable. A different executable or policy uses a new campaign directory. A root permutation must preserve exact tiny-tree minimax values when selective heuristics are disabled; playing strength and data yield remain measured questions.
