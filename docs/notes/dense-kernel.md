# Reusing activations across dense outputs

The arm64 path in `src/network_kernel.cpp` evaluates four output rows together.
Each activation vector is loaded once and used against four row-major weight
vectors. Every 128-input chunk widens its accumulated lanes into int64 before
adding biases or another chunk. A lane contains at most 32 products, bounded by
`32 * 2047 * 32768 < INT32_MAX`. Signed rounding and clipping match the original
per-row evaluator. Scalar and x86 paths retain the exact per-row implementation.

`tests/dense_kernel_test.cpp` independently computes every output with wide
scalar arithmetic across supported and remainder dimensions, both clipping
formats, signed weight extremes and rounding boundaries. The new executable
passed twelve native tests and the same tests under ASan/UBSan, 100000 trained
network transitions, 35840 interval observations and 2240 separate byte-reader
comparisons. It matched 3840 previous evaluator outputs and 32 fixed-node search
results. This change alters computation cost, not the numerical model.

`tests/dense_kernel_bench.cpp` alternates the two operators within one process.
Both execute the same deterministic changing activations and must return the
same signature. Ten paired trials of 10000 calls for each shape recorded actual
single-process CPU time separately from wall time. Median grouped/per-row CPU
ratios were 0.553 for 64 inputs and 32 outputs, 0.438 for 128/32, 0.424 for 256/32
and 0.584 for 32/16. These operator measurements do not establish a complete
engine speedup or an Elo gain. Whole-process microbenchmarks and the 120-search
cost profile ran under changing host contention and remain descriptive.

With the faster dense layers, the certified bound option's median paired search
time ratio was 0.997 for the ten-percent mixture. Its eight-percent inference
skip rate now has little observed whole-search benefit in this small profile.
The option remains disabled by default.

Two development failures are retained. The first metric driver used an absent
`--net-bench` flag; the implemented command is `--eval-bench`. The first paired
benchmark failed to compile because macOS uses unsigned `clock_t`. Its failure
sentinel now uses an explicit conversion and detects clock wrapping. Both
recoveries preserved their original cumulative wall deadlines. Earlier completed
correctness checks were not discarded or relabeled as new runs.

A separate sixteen-game, 100 ms resource pilot completed in 95.03 wall seconds
and 74.65 measured reaped-child CPU seconds while compilation and data work ran.
It retained four time-loss games, including three classical-control forfeits.
The apparent 9W/1D/6L score cannot establish board strength or neural contribution.
Full timed matches must run with controlled host load and retain any failures.
The original diagnostic network, its poor earlier timed results and the
unchanged classical evaluator remain intact.
