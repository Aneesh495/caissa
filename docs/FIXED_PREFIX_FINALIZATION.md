# Fixed-prefix data finalization

The original acquisition remains failed. A separately frozen six-hour finalization campaign can export and independently verify its retained corpus without generating a new game. [The active protocol](../config/data-finalization-v1.json) fixes the existing 114791-pair SHA256 manifest, original failure/history identities, teacher, held-out inputs, minimum data counts and searched-depth quality endpoint. [The earlier proposal](../config/data-finalization-v1.proposed.json) remains unchanged for chronology.

`tools/finalize_corpus.py` records the deadline once in `SCOPE.json`, owns a nonblocking writer lock and refuses an altered protocol, different source identity, renewed deadline or fourth attempt. Disk reserve and additional allocation limits are checked while child processes run. It holds the original corpus writer lock throughout. Export uses the existing committed SQLite transaction; the generation process never restarts.

A clean Git commit is archived before either stage. The export and independent verifier execute from that source snapshot with frozen holdout files, so later project development cannot alter a running campaign. Logs, progress and owner configuration use separate paths from copied source receipts. A resumed process uses the same source and original absolute deadline. Completed exports are immutable; interrupted exports preserve the committed source index and may be retried only within the remaining budget.

`verification/dataset.py` reconstructs every original legal game, outcome, family split, functional-input identity, feature row, target average and contributor. Recovery mode additionally checks the externally supplied protocol hash and exact original pair manifest. It rejects extra or missing journals, new acquisition sessions and any replacement of the original failed receipt with success. Its full mode still requires at least 100000 completed games, 10000000 distinct training inputs, nonempty validation/test splits and at least 95 percent of original samples with a completed search depth. It reads test arrays only for structural data reconstruction; no model or model-selection statistic is evaluated.

The checker publishes atomic game/array progress and retains its independent SQLite index for diagnosis. It has both a cumulative monotonic limit and the owner's absolute wall deadline. A killed, exhausted, malformed or incomplete run cannot produce a successful finalization receipt. A domain pass certifies data reconstruction only. Three full seeds, final-model numerical checks, neural contribution, external strength and the other project gates remain separate.

Nine scope controls cover competing owners, immutable resume state, changed inputs/budgets, expiry, clock rollback, allocation exhaustion and real child cleanup. Seven prefix controls retain actual small original games while rejecting weakened endpoints, changed protocol identity, added pairs, replacement of the original failure, new acquisition history, poor search quality and a full pass for an undersized corpus. Existing semantic array controls and process controls also pass. A test initially set its allocation allowance below the owner's own metadata size; that real failure is retained, and the corrected test stays inside its original cumulative development ceiling.

A full run is started with the frozen protocol hash and preserved pair-manifest path:

```sh
.venv/bin/python -m tools.finalize_corpus \
  --protocol config/data-finalization-v1.json \
  --expected-protocol-sha256 FROZEN_PROTOCOL_SHA256 \
  --pair-manifest PRESERVED_PAIR_MANIFEST \
  --corpus data/searched-full-v3 \
  --dataset data/searched-full-v3-prepared \
  --output runs/searched-full-v3-finalization-v1
```

Use `--resume` only against the existing scope, using its archived owner code if the working tree has since changed. A resume grants no additional wall time.
