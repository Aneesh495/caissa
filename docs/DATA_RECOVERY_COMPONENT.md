# Original data recovery component

This component uses only the already published original 56-pair diagnostic
corpus. It generates no games or labels and trains no model. It does not reopen
the original acquisition, full-data finalization or full-learning campaigns.

The preparer permits a diagnostic barrier only for the exact original corpus
configuration, pair count and content hash. It commits 32 source pairs, pauses
after staging 52 inside the next SQL transaction, and allows at most 15 seconds
at the barrier. The owner confirms that a separate connection still sees the
32-pair generation, preserves the raw SQLite/WAL boundary and progress files,
then records an actual SIGKILL and reap before resuming the original preparer.
Normal preparation retains its existing 100-pair transaction cadence.

The independent reader rebuilds every committed position, target and contributor
from the original first 32 game pairs. It checks the actual durable SQL cursor
and coupled counters, then independently reconstructs all 56 pairs and all three
final splits. Uninterrupted and resumed exports must match byte for byte and
retain the original published arrays. Rehashed semantic forgeries cannot replace
this reconstruction with a saved success flag.

The bounded producer has one 120-second wall/active ceiling, a 1 GiB output cap
and a 10 GiB reserve. The reader stages immutable evidence outside its original
directory and holds or inherits the exclusive host lease. The full-bundle adapter
reports a component only. Full G11 still requires all recovery components and
explicit final source/native-image binding.

[Hosted proof and retained failures](../results/g11-data-recovery-2026-10-26/README.md) record all 17 controls on both platforms. The first local execution failed on reader scratch setup; the first hosted execution reached a full-entry fixture directory collision. Both original failures remain preserved. The second and final allowed hosted execution passed. This development scope is closed and must not be rerun for status.
