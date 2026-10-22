# Commit checkpoint pointers after generations

Status: accepted for the implemented development system.

## Context

Overwriting best and last in place can leave a mismatched pair after interruption. Saving only model parameters cannot reproduce optimizer trajectories or sampling.

## Decision

Write immutable checkpoint generations with optimizer, scheduler and all RNG states. Fsync, then atomically publish one last/best hash pointer. A single-writer lock protects the transaction.

## Consequences and verification

Disk use is greater than keeping one checkpoint. Recovery restores pointer-selected generations and verifies bytes. Forced interruption must reproduce the uninterrupted final parameters rather than merely finish without an exception.

[Implementation](../../training/train.py) and [executed check path](../../tests/recovery.py). Execution scope and incomplete full gates are tracked in [build status](../BUILD_STATUS.md).
