# Publish completed search iterations

Status: accepted for the implemented development system.

## Context

Interrupted root work can mix exact scores and one-sided screening bounds or expose an empty best move before depth one. A GUI also needs stable MultiPV semantics.

## Decision

Retain a legal fallback immediately. Publish each fully completed root iteration; label one-sided lines. MultiPV searches complete the requested roots exactly rather than reusing a single-PV screening result.

## Consequences and verification

Cancellation can discard useful partial work. The last completed depth and total visited nodes are recorded separately. This favors understandable interruption semantics over speculative partial publication.

[Implementation](../../src/search.cpp) and [executed check path](../../tests/search_test.cpp). Execution scope and incomplete full gates are tracked in [build status](../BUILD_STATUS.md).
