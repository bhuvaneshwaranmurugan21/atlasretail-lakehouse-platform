# ADR 0001: Publish a generation, not individual tables

- Status: Accepted
- Date: 2026-08-14

## Context

An order generation is coherent only when orders, lines, payments, returns, inventory movements,
and product versions agree. Iceberg provides atomic commits and snapshot isolation for one table;
six successful table commits are not one cross-table business transaction.

## Decision

Every transformation writes to a generation-scoped physical state. After all quality gates pass, a
DynamoDB transaction advances the active-generation pointer only when its current version equals
the publisher's expected version. A failed or stale publisher cannot change the active generation.
Backfills follow the same construction and publication boundary.

## Alternatives considered

### Expose the latest snapshot of every table

Rejected because readers can observe snapshots from different pipeline attempts.

### Overwrite the serving tables after each successful task

Rejected because retries, partial writes, and concurrent publishers can expose mixed state.

### Coordinate publication with a single control-plane pointer

Selected because one conditional update can represent the visibility decision after cross-table
validation, while retaining failed generations for diagnosis.

## Consequences

- Readers need a generation-aware access path.
- Old generations require an explicit retention policy.
- Publication adds a control-plane dependency on DynamoDB.
- Pointer contention is visible as a stale-publisher failure rather than silent replacement.
- Physical table access must not be presented as the published serving interface.

## Current boundary

The local model validates publication, stale-writer rejection, replay, rollback, and backfill
isolation. The managed control plane requires a validated six-table snapshot set and exposes a
generation-pinned resolver. AWS run 33167646509 verified end-to-end publication, replay, injected
failure isolation, deterministic recovery, stale-writer rejection, and one generation-pinned
six-table serving resolution for its bounded workload.
