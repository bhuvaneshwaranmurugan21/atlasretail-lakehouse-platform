# Architecture decision record

## Decision

Use immutable landing manifests and generation-scoped Iceberg snapshots. The active analytical
product is a compare-and-swap pointer, never a mutable folder name.

## Workload model

The bounded AWS lab targets 1–3 GB of synthetic Parquet data and three controlled load points.
The production design assumes independent order, payment, return, inventory, and dimension
feeds; event time and knowledge time remain separate.

## Why Iceberg and Athena

Iceberg supplies atomic snapshots, schema evolution, partition evolution, and rollback without
requiring a persistent warehouse. Athena makes scan volume visible in each query execution. A
Redshift design becomes appropriate for sustained concurrency and predictable BI latency; it is
deliberately excluded from the bounded-cost experiment.

## Publication state machine

```text
LANDING -> VALIDATED -> BUILT -> PROVEN -> ACTIVE
               |          |        |
               +------> QUARANTINED
```

Every transition records the commit SHA, input manifest digest, contract version, run ID, row
counts, business totals, and service identifiers.

## Security boundary

Synthetic data only; S3 public access blocked; encryption at rest; TLS-only bucket policies;
GitHub OIDC instead of long-lived keys; project-scoped deploy and runtime roles; CloudWatch logs
retained for seven days and exported in sanitized form before teardown.

