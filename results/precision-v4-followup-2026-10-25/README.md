# Deployed loss and instrumented state replay

The q4096 encoding of the original selected float checkpoint retained validation-loss improvement and passed instrumented native checks on Linux x86-64 and macOS arm64. These are numerical, loss and systems observations. Playing strength and whole-project acceptance remain incomplete.

| Observation | Linux | macOS |
|---|---:|---:|
| Validation rows, original sorted selection prefix | 8192 | 8192 |
| Untrained residual loss | 0.410214411251 | 0.410214411251 |
| Actual deployed q4096 mixture loss | 0.402049260532 | 0.402049260532 |
| Release / ASan+UBSan / TSan native cases | 18 / 18 / 18 | 18 / 18 / 18 |
| Selected-model restoration transitions per mode | 1000000 | 1000000 |
| Independently reexecuted native cases | 54 | 54 |
| Independently reexecuted selected-model transitions per mode | 1000000 | 1000000 |
| Independent replay seconds, limit 600 | 490.137 | 470.352 |
| Total hosted job seconds across all three profile executions, limit 5400 | 1802 | 1627 |

The restoration modes use the same seeded million-transition workload. Repetition under different instrumentation does not create three million distinct positions. The deployed loss uses the same validation prefix as checkpoint selection, not a fresh test set. It combines outcomes and the original teacher's mean win probability at the original equal weighting. The selected seed, step, float checkpoint, mixture percentage and test isolation are unchanged.

The [first follow-up](https://github.com/Aneesh495/caissa/actions/runs/40167919374) ran at source `2fbac399b14bc6e0c51f92e812883abf22f44506`. It retained actual validation and instrumented-test logs. The [final follow-up](https://github.com/Aneesh495/caissa/actions/runs/40170041796), source `bebc3119b8c0022e307360a0a48ee2714f5f8f08`, additionally saved all nineteen native executables per mode, detailed CTest logs, commands, compilation flags and source identities. Its separate [checker](../../verification/precision_systems.py) verified those identities and reexecuted the exact saved programs, including the selected model. Its fifty-seven successful replay stages per platform comprise eighteen native cases and one selected-model restoration in each mode. The first follow-up's instrumented executables were not saved, so the final follow-up is the exact-program replay evidence; the two runs are not interchangeable.

The checker ran within the original precision scope and is deliberately constrained by that scope's original deadline. This is one completed experiment-stage replay, not a general portable whole-project verifier. Final cross-host reproduction and whole-project verification remain required. No later program is substituted for a missing saved executable.

The [publication checks](PUBLICATION_CHECK.json) recomputed both losses from all 8192 raw observations for both follow-ups/platforms, checked every saved and replayed program identity, all fifty-seven replay exits/log hashes per platform, and native source bytes against the trusted executable commit. [Hosted job records](HOSTED_JOBS.json) retain the actual durations and conclusions for all three profile executions. All finished before the original wall deadline. There are no job reruns, added games, model reselection or renewed resource ceilings.

The [archive index](ARCHIVES.json) pins the downloaded GitHub artifact digests and ordered archive parts. The [manifest](MANIFEST.json) hashes the published files. Both complete raw ZIPs are preserved for each follow-up. The larger final Linux ZIP is split into ordered 40 MiB parts to fit ordinary Git file limits. Reconstruct it without altering bytes:

```sh
cat results/precision-v4-followup-2026-10-25/independent-followup/linux/RAW.zip.part000 \
    results/precision-v4-followup-2026-10-25/independent-followup/linux/RAW.zip.part001 \
    results/precision-v4-followup-2026-10-25/independent-followup/linux/RAW.zip.part002 \
    > /tmp/caissa-precision-v4-linux.zip
shasum -a 256 /tmp/caissa-precision-v4-linux.zip
```

The reconstructed digest is `d7fba572176ec53210172cf1114a944340ed37706b1eb8e1c913f39ed0eae658`. Extraction supplies the original executable bytes and the exact per-mode `PROGRAMS.json` identities, raw observations and replay logs. The Mac archive is a single ZIP. The original q1024 failure is still failed, and the existing full strength comparison still uses that original frozen encoding. The q4096 encoding has no measured Elo result.
