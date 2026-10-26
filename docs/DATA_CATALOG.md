# Bounded original-data replay catalog

The data catalog separates immutable input admission/staging from the long
independent reconstruction. It keeps the existing full-bundle20GiB/one-hour
bounds and does not restart the closed corpus acquisition or finalization.

A frozen `caissa-original-data-catalog-v1` document names the trusted verifier
source commit, dataset identity, exact pair count, resource ceilings, input
views and every required destination file. Each view names an original input
directory and an externally pinned manifest of selected file hashes. Original
directories remain untouched. Other preparation indexes are neither consumed
nor claimed as verified. The original corpus namespace is checked separately
so a selected view cannot hide missing or additional paired games.
The frozen output path is part of the catalog; another output directory
cannot reset a completed or exhausted replay's resource ledger.

Full catalogs retain the exact114791-pair corpus, datasetf09, fixed-prefix
protocolf2bf and pair-hash manifesta68. They include all six arrays, all three
contributor-identity journals, original source-pair lineage, held-out files,
original corpus configuration and failed acquisition history. No successful
acquisition receipt may replace that original failure.

Full execution has one six-hour cumulative wall/active scope, at most one
attempt, one-hour staging,20GiB selected inputs,20GiB additional output and10GiB free
reserve, entirely inside the original project deadline. Each input view keeps
its own bounded immutable-read lease, while the single staging clock covers
them all. Streamed copies retain original hashes and enforce resource checks
between one-megabyte blocks. The independent reconstruction then runs from a
committed source archive, in its own bounded process group, against the private
copies and a newly owned SQLite index. It performs no game generation or
training. Full macOS runs require AC power and a scoped awake assertion.

The G07 data component passes only after the independent reader rebuilds every
original game, split, feature row, target average and contributor record at the
mandatory full floors. It still does not certify complete G07: the independently
replayed three-seed learning component must join the same dataset identity.
Other gates and the final whole-project audit remain separate.

The explicit diagnostic profile is limited to100pairs,120seconds and1GiB. It
cannot become a full component pass. Hosted integration uses the50 real native
CI pairs and independently replays their complete prepared dataset through
this new catalog path. Controls reject altered resources, false full promotion,
omitted/extra games, aliases, traversal, swapped arrays and rehashed source
forgeries. A legal-data hash update cannot bless an illegal original game.
These checks are not a full-corpus replay or a renewed historical budget.
An actual held timed-host lock must reject the catalog before it creates an
output scope. Output diversion is rejected without resetting the old ledger.
