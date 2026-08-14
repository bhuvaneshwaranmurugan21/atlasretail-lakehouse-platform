# ADR 0001: Publish a generation, not individual tables

- Status: Accepted
- Date: 2026-08-14

## Context

Independent table commits can expose an order generation before its payments, returns, inventory,
or dimensions have passed reconciliation. Iceberg provides table-level atomic snapshots but does
not make six separate table commits one business transaction.

## Decision

Every run writes to a generation-scoped namespace. After quality checks pass, a conditional
DynamoDB update advances the active-generation pointer. Athena serving views resolve only the
active generation. Backfills remain isolated until deliberately published.

## Consequences

Readers see a coherent retail generation and stale concurrent writers fail safely. The trade-off is
an additional control-plane object and explicit retention/cleanup for old generations.
