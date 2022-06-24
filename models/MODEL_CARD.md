# Diagnostic neural evaluator v2

This is an original randomly initialized Caissa model, trained on original selfplay. It is a diagnostic artifact, not the default evaluator or a strength release. The native executable loads it with `EvalFile` and `Use Neural`. No external engine supplied labels or weights.

Feature version 1, sixteen king buckets, two perspectives, active transformer width 64, nonlinear dense stages 32 and 16, q1024 arithmetic and activation clip 2047. The binary header binds the training checkpoint identity; the whole file is included in the trusted source-input manifest for diagnostic replay.

Dataset: 400 completed original games, 28534 raw samples, 16998 distinct usable positions. Splits: 13144 train, 2297 validation, 1557 reserved test. Game lineage and opening families determine splits; cross-split transpositions are quarantined. The test split was not used to select this artifact.

Training: seed 41, CPU, PyTorch 2.8.0, AdamW, learning rate 0.001, batch 512, 1000 updates, halfway transition to quantized-aware training. Among three diagnostic q1024 seeds, seed 41 had the lowest validation loss, 0.64394. Its saved checkpoint SHA256 is recorded in the model header. This is far below the required full-corpus experiment. It has no certified Elo advantage.

A 100000-position cross-language arithmetic run observed maximum floating/integer error 11.37 cp and bit-identical scalar/NEON outputs. The earlier coarse-quantization diagnostic lost badly to classical evaluation despite improved loss. Numerical agreement and lower validation loss are separate from playing strength.

The native engine does not require Python or another engine to use these weights. Training and isolated legality checks use separately pinned tools. The model and original generated data are offered under the project's MIT license. Independent third-party test tools retain their own licenses.


## Residual prefix diagnostic

`residual-prefix-diagnostic.cai` is another original diagnostic export, format 3, feature 1, widths 64/32/16, q1024, clip 2047 and classical contract 1. Its network SHA256 is `580ea83d33f54426981adc072042d4555bf26259a859ddafbc0bb0eb2f7b8926`; selected checkpoint SHA256 is `ae6fc9aa39b4900d7b932d76e2f72a70a0d4018d565eabe8b22825553a818a31`.

Seeds 17, 41 and 73 each completed 20000 updates on the older 2181990-input original diagnostic training split. That split predates functional reflection screening. Validation selected seed 17 at step 1000, loss 0.587335 against untrained 0.793343. The original classical terms remain inside the model contract. At full neural weight its 96-game equal-node pilot scored 8W/4D/84L against unchanged classical evaluation. It remains a negative diagnostic, with no release-strength or full-data claim. No external engine labels or pretrained network were used. [Settings and raw games](../results/residual-pilot-2026-10-22/MANIFEST.json) preserve the result.
