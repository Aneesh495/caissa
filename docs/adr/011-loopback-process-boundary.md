# Bound browser analysis ownership

Status: accepted for the implemented development system.

## Context

A local web page can still send cross-origin requests or abandon native work. Slow consumers can block protocol output and prevent an otherwise correct stop path from returning.

## Decision

Bind the service to loopback, require session token/origin checks, cap bodies/connections/workers and own each native child. Cancel stale generations. Bound native output and fail closed on critical overflow.

## Consequences and verification

The browser has explicit resource limits and overload failures. It is a local development interface, not authenticated multi-user hosting. Integration exercises real native processes, abort cleanup and malformed requests.

[Implementation](../../analysis-service/server.ts) and [executed check path](../../tests/service_integration.mjs). Execution scope and incomplete full gates are tracked in [build status](../BUILD_STATUS.md).
