# Artifact contracts

All JSON counts must be finite integers where declared. Every run uses a noncolliding directory. A manifest maps exact relative file names to SHA256; unsafe paths and symlinks are rejected by the verifier. Ordinary hashes prove byte integrity, not chess or statistical semantics.

A diagnostic evidence bundle contains `SOURCE_INPUTS.json`, `DATASETS.json`, `ENVIRONMENT.json`, `COMMANDS.jsonl`, `MANIFEST.json`, `ACCEPTANCE.json`, `COVERAGE.json`, raw perft/search/network observations, raw arena pairs, independent summary inputs, draw-history probes and the exact saved native executable/network. Source inputs are checked against a separately supplied trusted clean checkout and expected commit. The saved model must agree with the trusted original diagnostic model. Missing or additional artifacts fail inventory checks.

`verification/verify.py` independently replays legal PVs and games, checks result colors and draw reasons, interprets neural weights through `verification/inference.py`, recomputes opening-cluster statistics, and performs bounded native replay. `tools/negative_controls.py` creates validly rehashed copies with an illegal PV, swapped result, wrong neural output and false draw, then invokes the real verifier as a subprocess. Source mismatch, missing and corrupt artifacts are separate controls. The recorded exit and reason must show rejection.

Selfplay journals use `caissa-selfplay-v1`: pair identity, immutable command/configuration, two games, actual moves/results, terminal provenance and per-position original search metadata. Samples before deduplication are not unique-training counts. Prepared datasets use `caissa-dataset-v1`, canonical identity indexing, lineage/family split identities, quarantined transpositions and memory-mapped feature/target arrays.

Training uses immutable `checkpoints/step-N.pt` generations with full optimizer, scheduler and RNG state. `CHECKPOINTS.json` atomically selects last and best files by relative path and SHA256. Aliases can be repaired after interruption. Arena games are committed before pairs; derived PGNs can be rebuilt from already committed moves without replaying a game or changing its outcome.

Network binary contracts are specified in [quantization](notes/quantization.md) and [incremental features](notes/incremental-features.md). Model format compatibility is checked before search. Unsupported feature versions, active widths, numerical version combinations, lengths, biases and checksums are rejected.
