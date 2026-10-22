# Recovery runbook

Keep the exact executable, model, configuration and completed journals. A new binary or a changed budget requires a new corpus/match identity. Do not delete losing games to resume a campaign.

## Original corpus

Rerun the exact `training.corpus` command against the same output directory and frozen teacher. The immutable `CONFIG.json` rejects a changed executable or request. Completed pair files are validated and skipped. Temporary `.tmp` files have no completion meaning and can be inspected or removed after confirming no writer remains. The next atomic pair commit replaces only its own temporary path. A failed child must be investigated; do not turn a missing pair into a draw.

## Training

Rerun the exact training command with `--resume`. `TRAIN.lock` rejects a second live writer. `CHECKPOINTS.json` identifies complete immutable last/best generations and their hashes. Recovery restores those aliases, optimizer, scheduler, data sampler and CPU/device RNG. A torn temporary checkpoint is not referenced by the committed pointer. A configuration mismatch is an error. Keep both the best-validation generation and the last completed generation.

The forced-interruption test compares a killed/resumed run with an uninterrupted run and requires identical final parameters and selected checkpoint bytes. It also proves that completed corpus pairs survive a killed generator.

## Arena

Rerun the same `arena.run CONFIG OUTPUT` command. The source/model/opening/config hashes must match. Each game commits before its containing pair; a complete first game is reused after a crash between reversed colors. Missing PGN files are rebuilt from the saved legal transcript. The runner never silently restarts a completed losing game. Run `arena.statistics` again only after preserving the previous version of a summary if the statistical implementation changed.

## Analysis service

Cancel the current browser request or close its connection. The service owns its native process, sends stop and enforces a hard cleanup deadline. Start the service again with `make demo`. Versioned browser persistence stores PGN plus a variation path; the native parser reconstructs ownership on restoration. Invalid persistence resets visibly instead of trusting object pointers from storage.

## Evidence and release

Evidence run directories are immutable. Fix source, commit and use a new run ID after failure. Pass the trusted checkout and expected commit explicitly to the verifier. Hash repair cannot legitimize a changed chess result. A rejected full gate stays rejected. Only the full verifier and current maintainer audit permit release packaging.

Sources: [corpus](../training/corpus.py), [trainer](../training/train.py), [arena](../arena/run.py), [recovery tests](../tests/recovery.py), [arena recovery](../tests/arena_recovery.py).

## Prepared-data replay

`training.prepare --follow` consumes the fixed pair range while the original corpus writer is active. It never reads a temporary pair. The source SHA inventory, identity aggregates, contributor lineage, counts and histograms commit in one SQLite transaction every 100 pairs. A stopped corpus writer with a missing pair is an error, not successful preparation. The final NumPy arrays are exported only after the full requested range has been consumed.

After interruption, rerun the same preparation command with `--resume`. Completed source bytes are rechecked before reuse, and changed corpus configuration or held-out manifests are rejected. An interrupted array export is regenerated from the committed replay index. `DATASET.json` appears only after complete export and hashes; a completed dataset is immutable. A forced SIGKILL after the first 100-pair transaction reproduced every array and lineage byte and all counts/histograms from an uninterrupted 200-pair preparation.
