# Separate repetition and search identities

Status: accepted for the implemented development system.

## Context

A board hash is not a universal score identity. The same board can have different claimable draws, clocks and reversible histories. Null moves must not manufacture legal game repetitions.

## Decision

Keep a normalized repetition key and a conservative search key containing clock, reversible sequence and synthetic-search context. Reuse bounds only with the complete search key.

## Consequences and verification

This sacrifices conventional transposition reuse. A separate full-tag board hint stores only a move and verifies legality; it cannot supply a score. Bare FEN analysis starts with only the history it actually contains.

[Implementation](../../src/position.cpp) and [executed check path](../../tests/rules_test.cpp). Execution scope and incomplete full gates are tracked in [build status](../BUILD_STATUS.md).
