# Auditable native resource profiles

The v2 producer records actual UCI budget/history requests and timestamps alongside every timed search. Each native session retains its process ID, options, configuration commands and handshake. A bounded sampler records raw `ps` stdout, exit, process ID and start/end timestamps before converting KiB to bytes. Readiness and stop observations retain actual replies and request timestamps. Summary values do not stand in for these records.

`tools.performance` enforces wall and monotonic deadlines, position/repeat/thread limits, latency sample counts, hash bounds and output byte ceilings. The RSS sampler has a finite subprocess timeout, join timeout, response ceiling and sample ceiling. A failed sampler or incomplete producer writes a failed receipt. Existing evidence is never overwritten. `make profile` remains a diagnostic target and now enables both exact optimizations explicitly.

`verification.performance` imports neither producer parsing nor producer transport/statistics. It interprets raw native output, independently checks legal PVs and fallbacks, reconstructs request timing, validates allocated table/private-cache accounting and binds RSS to the actual process lifetime. Neural profiles must contain actual network inference and exact request/hit/miss accounting. Disabled bound and ordering options cannot appear as active counters. Sorted linear interpolation independently reproduces p50/p95/p99 values, and all throughput, depth, evaluator timing and per-position summaries are recomputed.

The checker additionally reruns every saved 10000-node scalar/native case with a separate bounded native transport. These deterministic queries must preserve best move, score, PV and completed depth. Timed searches and sampled RSS are measured populations, so their exact counts and durations are reconstructed rather than promised to repeat on another scheduler. Artifact size is checked before hashing, and externally supplied engine, model and workload bytes must remain unchanged during replay.

The diagnostic pilot used the unchanged frozen resource file: eight positions, five repeats, 250 ms per move, one/two/four/eight threads, 16 MiB hash, four evaluator modes and 1000 readiness samples both idle and active. The original corpus verifier was running. The older saved residual diagnostic model was used, with both exact optimization switches enabled and neural bounds/ordering hints disabled.

All 640 timed searches completed in 146.92 seconds. Independent reconstruction checked 5097 successful RSS samples, 2000 readiness samples and all 16 fixed-node scalar/native queries. The allocated table was 16777216 bytes throughout. Private evaluation-cache memory ranged from 524288 to 4194304 bytes with worker count. Maximum observed process RSS was 60424192 bytes. This includes native runtime, tables, model and workers; configured hash is not whole-process memory.

| Evaluator | Threads | Useful nodes/s |
|---|---:|---:|
| Classical | 1 | 1500757 |
| Classical | 4 | 2736106 |
| Classical | 8 | 3122024 |
| Ten-percent mixture | 1 | 1035802 |
| Ten-percent mixture | 4 | 2227192 |
| Ten-percent mixture | 8 | 2165908 |

These are total completed-iteration nodes divided by actual roundtrip time across the frozen workload. Eight-thread mixture throughput was lower than four-thread throughput in this loaded sample. Per-position depth and timing are retained; the easy mating fixture reaches the depth cap and is not evidence of broad search depth. Neither higher visited work nor this table establishes playing strength or linear scaling.

Observed readiness p99 was 0.02654 ms idle and 0.37360 ms active. The single stop observation was 0.15117 ms. A single stop is not a p99 estimate and does not replace the separate 10000-sequence adversarial protocol gate.

Thirteen actual CLI controls rejected rehashed corruptions: illegal PV, changed budget, fabricated request time, invented RSS, swapped RSS process, changed native counters, fabricated throughput, missing search, scalar-label swap, duplicated latency sample, diagnostic evidence presented as full, absent neural inference and an oversized artifact. Every failed invocation and mutated input identity is retained. They share the pilot's original 1200-second development ceiling; the 640 searches were not rerun or granted a renewed budget.

[Raw workload, sessions, process samples, timings, independent native replay and semantic controls](../../results/performance-v2-2026-10-24/) are preserved. Identical control inputs refer to the immutable base instead of duplicating it. Gzip files preserve byte-identical originals. The full checker requires the complete resource workload and rejects a diagnostic profile. Final selected-model measurements, controlled host load, parallel strength and race instrumentation remain separate pending evidence.
