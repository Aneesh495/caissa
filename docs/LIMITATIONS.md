# Limitations

The [v0.1.0 match](RELEASE_STRENGTH.md) measures relative Elo for the classical default under its hardware, openings and resources. It has no calibration to an absolute rating scale. The q1024 and q4096 neural results in [build status](BUILD_STATUS.md) used separate engines and match settings.

The learned evaluator scored below the classical evaluator in the matched comparison. The release includes the selected q4096 network as an optional experiment. The browser uses classical evaluation by default. King-bucket sparse features omit castling rights, en passant, rule clocks and history. Search owns those rule conditions; functional-input deduplication deliberately merges omitted distinctions before training splits.

A bare FEN cannot reconstruct repetition history or prove historical reachability. Structural validity checks reject many impossible states but do not solve general reachability. Conservative dead-position detection recognizes selected proven material patterns, not arbitrary fortresses. The engine claims current valid draws when the arena policy requests them; intended-move claims are not a general user-facing claim interface.

Root splitting shares a safe table and cancellation but has not demonstrated linear scaling or superior strength at every thread count. A mutex design and successful race instrumentation cover observed paths, not an unconditional proof of the whole program. Supported service budgets are intentionally smaller than arbitrary desktop UCI budgets.

There is no tablebase adapter, cloud execution, distributed trainer, opening book or imported engine code/weights. These are not runtime dependencies. Hardware-specific native kernels fall back to the scalar implementation where unavailable. Windows has not been validated.

The product release covers the engine, board and bounded strength benchmark. Full original research acceptance remains incomplete. See [build status](BUILD_STATUS.md) for the explicit gate state.
