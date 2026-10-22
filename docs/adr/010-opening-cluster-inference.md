# Infer strength using independent openings

Status: accepted for the implemented development system.

## Context

Treating repeated games from the same opening as independent narrows uncertainty artificially. An all-loss bootstrap also collapses to a misleading zero-width interval.

## Decision

Use color-reversed pairs, aggregate repeated opening families and bootstrap those clusters with fixed resampling seeds. Add a bounded-score guard when the observed bootstrap interval degenerates.

## Consequences and verification

Small opening sets can have very broad or censored intervals. That is reported instead of replacing endpoints with invented finite Elo values. Opponent settings do not establish an absolute rating.

[Implementation](../../arena/statistics.py) and [executed check path](../../tests/statistics_test.py). Execution scope and incomplete full gates are tracked in [build status](../BUILD_STATUS.md).
