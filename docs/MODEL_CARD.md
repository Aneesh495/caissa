# Selected original evaluator

Status: development model. Full playing-strength and release acceptance are incomplete. The browser and default UCI session use classical evaluation. The selected neural evaluator is experimental and requires explicit activation.

## Origin and selection

All parameters started from original random initialization. Training labels combine completed original game outcomes and searched scores from Caissa's original classical teacher at 2000 nodes per move. No external engine supplied moves, labels or network weights. Stockfish belongs only to the separate comparison arena.

The [independently reconstructed corpus](../results/full-data-2026-10-25/README.md) contains 229582 completed games and 10578434 distinct training inputs. Game lineage and opening families determine splits; functional-input equivalents shared across splits are quarantined. The dataset identity is `f09cdec986858c5b1aa80b3c97aaa4d825be892fc94e16ac5d835bc3d709f0ce`. The original failed acquisition and recovery receipts remain separate from the later successful data reconstruction.

Three seeds each completed 20000 updates with batch size 2048, checkpoint interval 250, learning rate 0.001, two CPU threads and pinned PyTorch 2.8.0. The objective gives equal weight to the outcome and mean original-teacher win probability. The model is trained for a ten-percent neural correction to the unchanged classical baseline. The selection workload is the first 8192 validation inputs sorted by input identity, rather than the entire validation array. Test arrays were not opened for selection.

| Seed | Completed updates | Selected checkpoint step | Recorded validation loss |
|---|---:|---:|---:|
| 17 | 20000 | 1500 | 0.4021646082 |
| 41 | 20000 | 1500 | 0.4024754837 |
| 73 | 20000 | 2750 | 0.4020510167 |

The [selection receipt](../results/full-model-v3-2026-10-25/SELECTION.json) retains all seeds, including later checkpoints with worse loss. Seed 73 at step 2750 remains selected. Its float checkpoint SHA256 is `c76d8e9ef0f2255531bc9085f5d0330a7a4152cf9b21a65ff8aee740ab8b2005`. [Independent learning verification](../results/full-model-v3-2026-10-25/INDEPENDENT_LEARNING.json) evaluated all 240 checkpoints and checked the saved initialization, parameter changes, baseline scores and optimizer provenance. This establishes actual learning and the declared selection procedure, not a positive Elo gain.

## Computation and encodings

The [model](../training/model.py) uses 12288 king-dependent piece-square features, a shared 64-wide sparse transformer evaluated from both perspectives, dense nonlinear stages of widths 32 and 16, and one residual output. [Native inference](../src/network.cpp) maintains sparse accumulators through make/unmake, refreshes the affected king perspective, and applies integer rounding, clipping and percentage truncation.

Two encodings of the same selected float checkpoint are preserved:

| Encoding | Scale and activation cap | Network SHA256 | Numerical result |
|---|---|---|---|
| Format 3 | 1024 and 2047 | `c251670ec53ba38a680c16cc6199be48f89cc829dd5483197e6d4b39ac6debf6` | Failed the full-model 32 cp limit at 57.055664 cp |
| Format 4 | 4096 and 8188 | `52d0306143392ad683c3ebb09fe013f34e1f9e2bc44d3aa153b32314207374b7` | Passed a fresh frozen 100000-probe sample; independent float64 maximum 10.394590 cp |

Format 4 preserves the real activation cap exactly. It changes the integer lattice and safe SIMD block width, without retraining or selecting another checkpoint. Its fresh probe maximum is not a paired comparison with the earlier failed sample. Both platform artifacts and the exact native executables are recorded in the [precision evidence](../results/precision-v4-2026-10-25/MANIFEST.json). The [precision note](notes/precision-v4.md) explains the arithmetic contract and its limits.

The [deployed-loss follow-up](../results/precision-v4-followup-2026-10-25/README.md) measured actual integer loss 0.402049260532 against the untrained residual's 0.410214411251 on the same original 8192 validation-selection rows. Both platforms also passed Release, address/undefined-behavior and thread instrumentation, then independent exact saved-program replay. These observations preserve the model choice and do not establish playing strength.

For a manual format 4 analysis, use a current build that supports that format and send these UCI options in order:

```text
uci
setoption name EvalFile value results/precision-v4-2026-10-25/selected-v4.cai
setoption name Neural Weight value 10
setoption name Use Neural value true
isready
position startpos
go nodes 10000
```

Wait for `uciok`, `readyok` and `bestmove` at their respective protocol boundaries. The generic UCI neural-weight default is 100, so the explicit value 10 is necessary for this trained mixture. Model loading rejects incompatible or corrupt files. The native executable needs no Python, network access or reference engine during analysis.

## Strength and limitations

The frozen 4000-game comparison uses the original format 3 executable and network throughout, followed by 2000 external games. A later format 4 deployment does not inherit those results as its own measured strength. No completed full-sample Elo estimate or absolute rating is available for either encoding yet. Earlier small neural pilots lost to classical evaluation and remain negative findings.

The original teacher is shallow, the labels depend on the declared adjudication policy, and validation loss measures prediction rather than search decisions. Higher integer precision can remove numerical error without improving moves. Selected-model strength, parallel behavior, controlled-host performance, final browser behavior and independent whole-project reproduction must pass their own gates before release.
