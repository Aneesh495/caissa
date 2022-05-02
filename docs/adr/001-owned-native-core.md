# Own the native rules and search

Status: accepted for the implemented development system.

## Context

A reference engine could supply chess behavior quickly, but would prevent independent original-engine claims. A browser-only implementation would also couple search scheduling to rendering.

## Decision

C++23 owns position, legal generation, notation, evaluation, search and protocol. Python is an isolated oracle and laboratory. TypeScript owns process/service/UI boundaries.

## Consequences and verification

The native executable runs without network or Python. Independent validation remains necessary because original code can share systematic mistakes. Importing an external engine as a hidden runtime fallback is outside this decision.

[Implementation](../../CMakeLists.txt) and [executed check path](../../tests/core_test.cpp). Execution scope and incomplete full gates are tracked in [build status](../BUILD_STATUS.md).
