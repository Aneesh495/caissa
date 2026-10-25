# Draw-history instrumentation and retained first failures

At source d2e2d9668351891afddccc5cdf8f86f8c549e41f, workflow40197994490 passed all four Linux/macOS ASan+UBSan/TSan jobs. Independent read-only archive checks verified actual flags, program hashes, all20native cases,92history/2195observation G03replay and12controls. The complete84MBraw archive set is retained locally and pinned in RAW_RETENTION.json; bulk copies are not included in this compact distribution.

The preceding40197868753 run failed on both platforms and both instrumentation modes because the frozen v1profile requested illegal nonzero EP clocks. Its actual four job logs are included without relabeling their failures. The corrected v2profile and same-budget local proof were published separately. These are D2native/source identities before the later5803 intended-claim search repair. That new image has its own current instrumentation run.
