# Represent rights by rook origin

Status: accepted for the implemented development system.

## Context

Classical KQ flags alone do not encode Chess960 rook origins. Moving king then rook with ordinary square updates can destroy overlapping pieces.

## Decision

Store one rook-origin square per color and wing. Generate the final king and rook placements as a coordinated transition, with explicit attack-path semantics.

## Consequences and verification

Standard and Chess960 share one state model. Undo must restore at most four distinct touched squares and every rights field. Variant selection is explicit, because an isolated notation string is insufficient.

[Implementation](../../src/movegen.cpp) and [executed check path](../../tests/position_test.cpp). Execution scope and incomplete full gates are tracked in [build status](../BUILD_STATUS.md).
