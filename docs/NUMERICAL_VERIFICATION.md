# Saved-model numerical replay

`tools/network_audit.py` freezes reachable probe FENs before inference, records model, checkpoint, executable and input hashes, and compares scalar, selected native and NumPy integer outputs. `verification/numerical.py` reads those observations without importing training code. It independently reconstructs the seeded legal walk, validates the exported bytes against the checkpoint, evaluates its own integer graph, evaluates the saved float32 parameters through a separate float64 graph and reruns every FEN through the exact saved executable.

The numerical contract has two endpoints. Raw quantization error compares the unclamped floating and integer scores. Inference error compares their scores after the engine's reserved-mate clamp at ±29871 cp. Both must satisfy the frozen bound. This distinguishes intentional score clipping from precision loss while preventing clipping from concealing numerical error. A failed bound keeps its complete observations and failed summary; both producer and verifier return a nonzero exit. A saved pass flag has no authority over recomputed errors.

The verifier checks every scalar/native/reference value, input order, floating value, error, mean, p99 and maximum. Its float64 graph must agree with the producer's float32 graph within 0.01 cp. Native replay owns a separate process group, with a 120-second wall and monotonic deadline, 128 MiB stdout and 1 MiB stderr limits. The outer audit also has a finite cumulative deadline. Full-domain verification additionally requires the prospectively frozen protocol, 100000 probes and external selected-network/checkpoint identities. This domain alone cannot issue project acceptance.

The retained original diagnostic residual model passed 100000 probes: 96900 unique FENs; exact integer agreement; mean 1.98958 cp, p99 5.74323 cp and maximum 12.19702 cp. Independent float64 maximum error was 12.19705 cp. Maximum float32/float64 difference was 0.000581 cp. No probe clipped its output. These results justify retaining a 32 cp endpoint for a later full-data model; that model still has to pass it. The model was trained on an older diagnostic prefix and cannot satisfy full learning acceptance.

Seven rehashed controls reject altered integer results, floating values, unclamped quantized scores, reordered input manifests, false statistics, contradictory status and an undersized full sample. A separately frozen 0.001 cp diagnostic bound deliberately fails on 1000 real probes. Both programs preserve all 1000 observations and the independent error distributions while returning 1.

A later repeat of the existing 100000-probe replay did not finish. The host accumulated 905.88 seconds of wall time during 6.52 monotonic seconds; the process owner enforced the declared deadline and retained exit -15. Its 600-second phase budget remains exhausted. This is a failed followup, not a replacement for the earlier completed sample. Focused tests of the newly added failure-accounting paths are recorded separately. No final-model pass follows from either run.

[Raw observations, failed followup and endpoint controls](../results/numerical-replay-2026-10-23/) include a byte-exact gzip copy of the diagnostic checkpoint, FENs, probes and identity receipts. `IDENTITY.json` maps compressed files to original hashes. Sample CONFIG files retain their actual precommit source hashes. The accompanying current-source snapshot includes subsequent failure-accounting changes; the interrupted repeat does not establish a completed 100000-probe run of that snapshot.

To replay a decompressed observation directory and checkpoint with the original matching executable:

```sh
.venv/bin/python -m verification.numerical OBSERVATIONS \
  --engine MATCHING_CAISSA --network models/residual-prefix-diagnostic.cai \
  --checkpoint DIAGNOSTIC_SELECTED.pt --max-seconds 900
```
