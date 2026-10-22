# Use defined concurrent table access

Status: accepted for the implemented development system.

## Context

A lock-free table made of ordinary concurrently accessed C++ fields is a data race, even if occasional torn entries appear tolerable during play. Per-worker tables avoid races but abandon shared work.

## Decision

Use fixed buckets, full tags and striped mutexes. Copy entries while locked and release before recursion. Bound allocation to the requested Hash budget, including move hints.

## Consequences and verification

Contention and conservative history keys may reduce speed. Race instrumentation and 1/2/4/8 resource/strength profiles are separate evidence requirements. No scaling claim follows from the ownership design alone.

[Implementation](../../src/table.cpp) and [executed check path](../../tests/table_test.cpp). Execution scope and incomplete full gates are tracked in [build status](../BUILD_STATUS.md).
