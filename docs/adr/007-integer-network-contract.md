# Version quantized arithmetic

Status: accepted for the implemented development system.

## Context

The first q64 trained export showed unacceptable float/integer error. Silent scale changes would make existing weights ambiguous. Wide products can overflow narrow SIMD lanes on valid extreme inputs.

## Decision

Retain v1 compatibility and add q1024/clip2047 v2. Specify feature dimensions, scales, clipping, payload size, identity and CRC. Accumulate bounded product chunks, then widen to int64.

## Consequences and verification

Larger scale improves the measured diagnostic error but does not prove final-model accuracy or strength. Export/load rejection and independent integer inference remain mandatory. Wrong dimensions fail before search starts.

[Implementation](../../src/network.cpp) and [executed check path](../../tests/kernel_test.cpp). Execution scope and incomplete full gates are tracked in [build status](../BUILD_STATUS.md).
