# Paired strength inference

`arena/run.py` runs each opening with the candidate playing both colors. Engine executables, network bytes, options and opening manifests are frozen. A crash, protocol failure, illegal move or time loss is an outcome, not a removable outlier. Each game is journaled before its pair, allowing an interrupted second game to resume without repeating the completed first game. Unfinished ply-limit games remain visible and prevent a complete-sample claim.

`arena/statistics.py` converts each completed pair to its mean candidate score. When an opening is repeated, all its pairs form one bootstrap cluster. Treating repeated deterministic openings as new independent evidence would narrow the interval incorrectly. Bootstrap resampling draws opening clusters with replacement and divides summed scores by summed pair counts, preserving the observed game weighting. Twenty thousand resamples with seed 104729 define the percentile interval.

For score probability p, relative Elo is `400 log10(p/(1-p))`. This monotone transformation carries score uncertainty into rating uncertainty. At score endpoints the interval is unbounded. The first neural diagnostic yielded a relative estimate of -416.6 Elo, with an unbounded lower limit and upper limit -254.7, over twelve independent opening clusters. These are conditional diagnostic differences at a 2000-node budget, not an absolute rating or a full campaign result.

`verification/verify.py` independently replays games and recomputes cluster statistics. Summary pass flags have no authority. Stockfish's configured strength settings are reference conditions; they do not automatically calibrate an absolute rating for another engine or time control.

## Independent replay of complete campaigns

`verification/strength.py` streams paired journals, independently checks opening schedule, actual move observations, result colors and every recorded principal variation, then recomputes opening-cluster statistics. New journals retain the exact UCI position/history and go command with monotonic start/end timestamps. Full verification checks those commands against the frozen time and resource policy and the actual preflight option declarations. The classical control must use the same executable and unrelated search options with neural evaluation disabled.

Derived floating-point Elo transforms allow 1e-8 absolute arithmetic tolerance; counts and censored endpoint strings remain exact. This accommodates independent summation rounding without changing any statistically meaningful endpoint. Full contribution verification refuses protocols below 2000 pairs, estimated gain 50 or a strictly positive lower limit. A censored all-win estimate can satisfy the endpoint only when its independently guarded lower interval does. Failed contribution is an explicit rejection with its observed statistics retained.

The checker separately reproduced the warm unrestricted Stockfish all-loss sample, the strength-limited sample and the negative larger neural pilot. Synthetic integration campaigns exercise rejections for malformed PVs, changed actual go budgets, swapped colors and missing raw observations. Synthetic games remain integration evidence and never count as measured engine strength.
