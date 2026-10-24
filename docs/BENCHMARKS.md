# Benchmark methodology

A faster executable has no automatic Elo conversion. Freeze source, compiler/options, executable and network SHA256, positions, budgets, host and competing load before interpreting comparisons. Keep diagnostics under contention separate from isolated acceptance.

## Resource profiles

```sh
python -m tools.performance --engine build/caissa --network models/diagnostic-v2.cai --output runs/profile-001 --load-note 'Describe actual competing host work here' --diagnostic --exact-optimizations --maximum-seconds 1800
```

The checked `config/performance.json` fixes eight positions, five repeats, 250 ms searches, one/two/four/eight threads, 16 MiB and 1000 ready-command samples. The profiles cover classical, pure scalar neural, pure native neural and the ten-percent experimental mixture. Each fresh client warms up, then each position clears game/table state. All actual best moves and PVs are independently replayed. The original UCI transcript is retained.

Record visited nodes, nodes at the last completed depth, depth/selective depth, evaluator/cutoff counters, elapsed time and actual allocated table bytes. Resident set samples come from the owned native process, including its runtime and workers. Hash size is not process RSS. A memory sampler failure is an error. Depth is summarized per position: a trivial mating position can reach the depth cap and must not inflate a general search-depth claim.

The same positions also run at exactly 10000 nodes with one thread under scalar and native neural inference. Best move, completed depth, score and PV must agree. These fixed-node signatures test equal semantics; timed runs can legitimately complete different depths. The saved correctness file and both raw measurement streams are SHA-bound into the summary.

Ready latency is recorded both idle and during an active search. Stop latency is measured separately. Percentiles describe the observed command population and declared load. The larger adversarial 10000-sequence protocol campaign remains a separate gate; a hundred quick development samples do not replace it.

## Compiler and evaluator pilots

Release builds request supported compiler interprocedural optimization through CMake's capability check. Unsupported toolchains fall back visibly. `-DCAISSA_LTO=OFF` provides the matched compiler control. Sanitizer builds disable this optimization. One hundred fixed-node searches and the native correctness suite preserved their semantics in the initial IPO comparison.

The initial evaluator microbenchmarks ran while corpus generation and preparation competed for CPU. Classical timing was lower in the IPO binary, while native neural timing was higher in that particular order. Those samples do not establish a stable speedup. Run alternating repetitions on an otherwise controlled host before claiming one. `--eval-bench NETWORK CALLS` retains a consumed result signature to prevent an unused loop from disappearing.

## Strength and ablations

Use one frozen source executable for both sides of a heuristic/evaluator comparison. Change only the declared option. Preserve baseline evaluation weights, resources, openings, warmup and adjudication. Report all failures. Compare equal time for product strength and a separate equal-node experiment for information quality. For parallelism, compare strength as well as total nodes and useful completed work.

Opening families are the independent statistical units. Color reversal controls side assignment; repeated use of one family does not create independent openings. Use the predeclared fixed sample, confidence method and endpoint censoring from the experiment protocol. Archive failed and inconclusive hypotheses. Do not select a seed using test results or silently switch statistical procedures after a favorable sample.

The [v2 resource profile](notes/resource-profile-v2.md) retains raw RSS and actual request/latency timestamps. `verification.performance` independently reconstructs those observations and reruns saved scalar/native probes. The older diagnostic model completed the full 640-search resource workload under active corpus replay; it is not final selected-model or isolated-host acceptance.
