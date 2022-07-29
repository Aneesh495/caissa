# Training at the deployed neural percentage

The earlier networks optimized their full neural output and were later mixed at
ten percent during play. `--neural-weight` now lets residual training optimize
and validate the declared mixture directly. Its default of 100 preserves the
existing experiments. Lower percentages require residual format 3 and the
original classical baseline arrays. The new configuration records both the
percentage and its arithmetic contract.

`training/model.py` applies the native full-score clamp before mixing. During
quantized-aware training, straight-through output rounding and signed percentage
truncation retain gradients at the declared percentage. Native evaluation stays
integer and separate. Hidden-layer QAT remains a floating approximation; this
training objective does not replace the final independent numerical-error gate.
The zero residual still produces exactly the original classical baseline.

Twenty-five known output cases covered signed half ties, percentage truncation
and saturation. Autograd checks confirmed gradients at five percentages and
zero gradients after saturation. A separate historical-source comparison ran
200 updates with the old and new default objective: parameters, optimizer,
scheduler, sampler, Python/NumPy/Torch RNG, validation and configuration matched
exactly. Resuming the completed historical budget kept its configuration and
original initialization bytes. This does not claim a new forced-interruption
recovery campaign.

The new three-seed diagnostic used the stronger original teacher's 400-game
pilot: 17654 training inputs and 2563 validation inputs, seeds 17/41/73, 1000 real
updates each, batch 512, CPU with two threads, and four checkpoints per seed.
Test arrays were not opened. All seeds overfit this small sample:

| Seed | Untrained validation loss | Best trained validation loss |
|---|---:|---:|
| 17 | 0.37834248 | 0.38147594 |
| 41 | 0.37834248 | 0.38170146 |
| 73 | 0.37834248 | 0.38182412 |

The independent checker rejected the learning-improvement endpoint. Its first
failure stopped at the first seed. The checker now completes the provenance
audit for every seed and export before returning the same failed endpoint with
all observed losses. It independently evaluated all twelve checkpoints and
verified optimizer/sampler/initial-state lineage. A positive older learning
sample still passed; four rehashed semantic mutations still failed for their
intended reasons. This forensic continuation did not retrain, change selection,
extend the original wall ceiling, or turn a negative result into a pass.

No playing-strength claim follows from these losses. The stronger data and the
failed smaller prototype remain separate from the pending full three-seed
campaign. Classical evaluation remains the default.
