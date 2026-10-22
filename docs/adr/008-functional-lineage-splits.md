# Split by lineage and actual neural input

Status: accepted for the implemented development system.

## Context

Random position splitting leaks neighboring games and transpositions. Exact FEN matching also misses identical evaluator inputs when omitted rights/clocks differ or mover-oriented color reflections coincide.

## Decision

Assign the opening family to one split. Hash side-to-move-normalized placement, aggregate same-split labels and quarantine every cross-split collision. Screen frozen studies/opening inputs before training.

## Consequences and verification

Some otherwise useful observations are discarded. Targets average conflicting outcomes rather than depending on first encounter. Lineage retains contributing games. Legacy prepared data remains diagnostic and is never relabeled as screened.

[Implementation](../../training/prepare.py) and [executed check path](../../tests/features_test.py). Execution scope and incomplete full gates are tracked in [build status](../BUILD_STATUS.md).
