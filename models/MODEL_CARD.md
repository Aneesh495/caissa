# Diagnostic neural evaluator v2

This is an original randomly initialized Caissa model, trained on original selfplay. It is a diagnostic artifact, not the default evaluator or a strength release. The native executable loads it with `EvalFile` and `Use Neural`. No external engine supplied labels or weights.

Feature version 1, sixteen king buckets, two perspectives, active transformer width 64, nonlinear dense stages 32 and 16, q1024 arithmetic and activation clip 2047. The binary header binds the training checkpoint identity; the whole file is included in the trusted source-input manifest for diagnostic replay.

Dataset: 400 completed original games, 28534 raw samples, 16998 distinct usable positions. Splits: 13144 train, 2297 validation, 1557 reserved test. Game lineage and opening families determine splits; cross-split transpositions are quarantined. The test split was not used to select this artifact.

Training: seed 41, CPU, PyTorch 2.8.0, AdamW, learning rate 0.001, batch 512, 1000 updates, halfway transition to quantized-aware training. Among three diagnostic q1024 seeds, seed 41 had the lowest validation loss, 0.64394. Its saved checkpoint SHA256 is recorded in the model header. This is far below the required full-corpus experiment. It has no certified Elo advantage.

A 100000-position cross-language arithmetic run observed maximum floating/integer error 11.37 cp and bit-identical scalar/NEON outputs. The earlier coarse-quantization diagnostic lost badly to classical evaluation despite improved loss. Numerical agreement and lower validation loss are separate from playing strength.

The native engine does not require Python or another engine to use these weights. Training and isolated legality checks use separately pinned tools. The model and original generated data are offered under the project's MIT license. Independent third-party test tools retain their own licenses.
