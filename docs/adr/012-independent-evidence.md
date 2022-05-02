# Require source-bound semantic verification

Status: accepted for the implemented development system.

## Context

A checksum proves byte consistency, not chess truth. A collector can faithfully hash a wrong PV, swapped colors or an invalid draw declaration.

## Decision

Anchor verification to an explicitly trusted checkout/commit. Recompute game legality, result colors, network outputs and opening-cluster statistics independently. Rehash semantic corruptions before testing rejection.

## Consequences and verification

Verification takes real replay work and diagnostic scope cannot certify a full release. Full acceptance remains blocked while required raw campaigns are missing or failed. A pass boolean inside a bundle is not authority.

[Implementation](../../verification/verify.py) and [executed check path](../../tools/negative_controls.py). Execution scope and incomplete full gates are tracked in [build status](../BUILD_STATUS.md).
