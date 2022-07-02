# Independent learning verification

A training summary is a claim. [The separate checker](../verification/learning.py) reads the actual saved initialization, every declared validation checkpoint, optimizer state, scheduler position, sampling state and selected export. It imports no training implementation, performs no gradients and never opens test arrays. Original game legality, split/target reconstruction and playing strength remain separate checks.

The trainer now writes `initial.pt` and `INITIAL.json` before its first update. They identify the seed, exact random parameters, configuration and untrained validation loss. Earlier diagnostic runs without this original artifact cannot be retroactively promoted to complete learning evidence. Resume retains the existing initialization. `CHECKPOINTS.json` still commits immutable best/last generations and their byte identities.

The checker reconstructs sparse placements through Python-chess, checks both perspectives and independently evaluates every saved checkpoint on the prescribed validation prefix. A separate tensor graph implements clipped dense stages and stable binary cross entropy. It verifies the actual best step and seed ordering. The loss tolerance is 0.00002 absolute, allowing float32 summation differences between batch shapes and loss implementations. The small observed differences were below 0.00000003. This tolerance does not apply to integer inference or selected export bytes, which remain exact.

For residual models it recomputes classical scores on all selected validation positions and a fixed seeded sample of training inputs. It checks baseline manifests, source executable identity, array dimensions and hashes. Those sampled score checks complement complete data reconstruction; they do not pretend to replay all baseline generation calls. Baseline probe selection uses seed 86028157 and at most 4096 training draws, with repeated indices checked once.

AdamW moments must cover every model parameter with finite values, nonnegative second moments and the correct step. The scheduler must have the declared cosine position and learning rate. The checker replays random sampling draws without loading training examples or optimizing weights, then compares exact saved generator states. It checks RNG readability, real parameter changes, checkpoint chronology and held-out improvement over the original initialization. Safe checkpoint loading has an explicit numerical type allowlist and a 128 MiB file bound.

The export check independently rounds each selected tensor and compares every binary weight, bias, scale, dimension, checkpoint identity and checksum. Rehashing a changed network cannot make it correspond to a different selected model.

A real diagnostic trained seeds 17, 41 and 73 for 100 updates each, evaluated all six saved checkpoints on 2297 validation positions and independently checked 5802 baseline scores. Four subprocess controls rejected a changed validation loss, altered sampler, false optimizer step and rehashed exported weight for their respective semantic reasons. A full-mode attempt rejected this small dataset. [Observed receipts](../results/learning-checker-2026-10-22/INDEPENDENT.json) retain these limits. This proves a bounded checker path, not full training or positive Elo.

```sh
.venv/bin/python -m verification.learning \
  --dataset data/diagnostic-v2-final-screened \
  --runs runs/learning-independent-pilot/seed17 \
         runs/learning-independent-pilot/seed41 \
         runs/learning-independent-pilot/seed73 \
  --selection runs/learning-independent-pilot/selection \
  --baseline runs/small-classical-baselines
```

Full learning additionally requires the actual data floors, functional split screening, the frozen protocol and every declared seed with identical numerical settings. The complete project verifier must independently bind these artifacts to trusted source and run the original-game and strength checks. A domain checker never sets complete project acceptance.


## Relocated artifacts

`CHECKPOINTS.json` and its immutable generation files are authoritative. Optional `best.pt` and `last.pt` shortcuts are checked if present; their absence does not erase the saved generations. A missing required generation or a present shortcut naming different bytes still fails. Recorded origin folder names remain provenance text. Only explicitly supplied directories locate inputs; model hashes, seed identities, numerical settings and validation ordering remain mandatory.

The clean Linux diagnostic executed twelve stages, 400 original games, three seeded runs and native inference checks. Its downloaded artifacts independently replayed on macOS without recreating checkpoints or editing selection metadata. Original data/targets, all saved validation checkpoints, exact selected export and 1000 numerical probes passed. The source inventory was checked against trusted commit `1e5d59ac68282cf46bfcde792ba26309244854e1`, obtained from the hosted run. [Raw receipts and controls](../results/linux-learning-2026-10-22/MANIFEST.json) retain the initial missing-shortcut rejection, successful canonical replay, mandatory-generation and wrong-shortcut failures, and four repeated semantic mutations.

This is replay of saved results across platforms. It does not assert bit-identical retraining between ARM and x86 or between different PyTorch builds. Full data, final-source acceptance and playing strength remain separate.
