# Execution walkthroughs

## FEN to a native best move

`apps/main.cpp` enters `uci_loop` in `src/uci.cpp`. A position command parses six FEN fields with `Position::from_fen`, then applies each supplied legal UCI move. This retains repetition history rather than reparsing the final board. A go command validates resources and initializes cancellation/ponder state before starting its owned coordinator. `Search::run` obtains legal roots, checks termination and starts iterative deepening. Worker visits use scoped make/unmake, context-safe table bounds and classical or explicitly enabled neural evaluation. A completed depth is published; interruption returns the last completed result or the initial legal fallback.

## Move to sparse neural evaluation

`Position::make` records old pieces at every touched square and updates the board hash. A search guard calls `Network::update` in `src/network.cpp`. An unchanged king bucket receives old-row subtraction and new-row addition. A changed bucket is rebuilt from all active pieces for that perspective. `Network::evaluate` verifies the ownership key, clips both accumulators, orders them by side to move and executes two nonlinear dense stages. Integer kernels in `src/network_kernel.cpp` retain a scalar path. Unwinding restores the saved accumulator and position together.

## Selfplay to a selected checkpoint

`training/corpus.py` launches bounded `--selfplay-pair` commands. `src/selfplay.cpp` records moves, original search targets and actual terminal provenance. Atomic journals preserve pairs. `training/prepare.py` independently replays games, screens transpositions and writes disjoint memory-mapped splits. `training/train.py` updates randomly initialized parameters, evaluates validation loss and writes immutable checkpoint generations. One atomic transaction references both last and best generations. `training/export.py` writes the numerical contract, training identity and payload checksum. Selection never opens the test split.

## Cancellation and recovery

The browser in `web/app.ts` aborts an old request when its selected variation changes. `analysis-service/native.ts` writes stop/quit to its UCI child and bounds teardown with a kill fallback. The native session joins all search workers before releasing the position or table. Stale browser frames are discarded by generation identity. Training recovery follows `CHECKPOINTS.json`, verifies generation hashes and rebuilds aliases after a kill between pointer publication and alias replacement. `tests/recovery.py` forced SIGKILL and compared resumed parameters and the best checkpoint with an uninterrupted run. It also killed a real corpus writer, inserted a torn temporary file and verified that completed paired bytes were preserved.
