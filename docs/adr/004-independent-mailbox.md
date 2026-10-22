# Use a structurally different move oracle

Status: accepted for the implemented development system.

## Context

Two bitboard generators sharing attack tables can agree while repeating the same bug. An external oracle alone would also hide internal coupling failures.

## Decision

Maintain an independent 10x12 mailbox generator and application path. Compare it with bitboards and a separate Python chess implementation on seeded reachable positions.

## Consequences and verification

The reference path is slower and excluded from normal search. It provides useful diversity, not a mathematical proof. Every mismatch is fatal to its campaign and preserved for diagnosis.

[Implementation](../../src/reference.cpp) and [executed check path](../../tools/differential.py). Execution scope and incomplete full gates are tracked in [build status](../BUILD_STATUS.md).
