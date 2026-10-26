# Original learning replay component

The `original-learning-v1` G07 driver replays the original three training runs.
It retains the actual frozen v3 protocol, MODEL_CAMPAIGN.json, validation-only
SELECTION.json, original q1024 network and selected float checkpoint. It does
not rewrite a receipt to describe the deployed q4096 network. Both encodings
must name the same validation-selected float checkpoint, and the original
failed numerical domains remain visible in the lineage record.

The `original_learning` descriptor references its original `protocol`,
`model_campaign`, `network` and `checkpoint`, plus complete `dataset`,
`baseline` and `seeds` inventories. The dataset component supplies train
features and validation features/targets. Test arrays are forbidden here.
Each of seeds17/41/73 supplies its original configuration, initialization,
initial identity, observations, summary and all80 chronological checkpoints.
The original transaction metadata must name the actual best/last bytes.
All files must be present in the immutable manifest and G07's declared inputs.

Large arrays and checkpoints stream into new external files through verified
file descriptors, with one-megabyte reads, original byte/time ceilings and
before/after identity checks. The independently implemented learning reader
then checks initialization ancestry, optimizer/sampler/configuration state,
all240 saved validation results, the original classical baseline, actual
parameter changes and validation-only selection. It performs no training.
The caller's original cumulative wall/active deadline bounds the entire child.
Input file stamps are checked again after execution.

A successful learning replay is a G07 component pass, never a complete G07
pass. The full original-data reconstruction must independently pass and join
the same dataset identity. The coordinator keeps G07 pending until that joint
audit exists. A failed loss-improvement endpoint stays failed with its actual
observations; process and artifact failures are rejected.

The hosted controls admit only the real published original lineage, then use
the actual full command to reject rewritten receipts, changed protocols or
selection, a borrowed deployment network, different float parameters, changed
training settings, missing raw work, test-array inputs, omitted seeds and
missing checkpoints. Their fixtures never evaluate a tensor or certify a
learning component. Full-size replay and the data join remain required.

The lineage controls and all ten full-command rejections passed on Linux and
macOS at sourcec8aa443, correctness run40216641588. The real9MiB streaming-copy
case used about2MiB peak Python memory on each platform; all nine copy controls
passed. [Complete logs and exact identities](../results/learning-bundle-2026-10-25/VERIFICATION.json)
retain those bounded outcomes. No tensor inference or complete learning replay
ran in these fixtures.
