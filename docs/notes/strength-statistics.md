# Paired strength inference

`arena/run.py` runs each opening with the candidate playing both colors. Engine executables, network bytes, options and opening manifests are frozen. A crash, protocol failure, illegal move or time loss is an outcome, not a removable outlier. Each game is journaled before its pair, allowing an interrupted second game to resume without repeating the completed first game. Unfinished ply-limit games remain visible and prevent a complete-sample claim.

`arena/statistics.py` converts each completed pair to its mean candidate score. When an opening is repeated, all its pairs form one bootstrap cluster. Treating repeated deterministic openings as new independent evidence would narrow the interval incorrectly. Bootstrap resampling draws opening clusters with replacement and divides summed scores by summed pair counts, preserving the observed game weighting. Twenty thousand resamples with seed 104729 define the percentile interval.

For score probability p, relative Elo is `400 log10(p/(1-p))`. This monotone transformation carries score uncertainty into rating uncertainty. At score endpoints the interval is unbounded. The first neural diagnostic yielded a relative estimate of -416.6 Elo, with an unbounded lower limit and upper limit -254.7, over twelve independent opening clusters. These are conditional diagnostic differences at a 2000-node budget, not an absolute rating or a full campaign result.

`verification/verify.py` independently replays games and recomputes cluster statistics. Summary pass flags have no authority. Stockfish's configured strength settings are reference conditions; they do not automatically calibrate an absolute rating for another engine or time control.
