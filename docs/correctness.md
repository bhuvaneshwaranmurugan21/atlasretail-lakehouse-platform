# Correctness model

AtlasRetail publishes a retail generation only when its input identity, six physical datasets, and
cross-table business rules agree. This document distinguishes the required invariant from the
environment in which it is currently enforced.

## Batch identity

| Requirement | Behaviour |
|---|---|
| Stable identity | A batch ID is permanently associated with one canonical manifest digest |
| Idempotent redelivery | The same batch ID and digest has one business effect |
| Conflicting reuse | The same batch ID with another digest is rejected |
| Manifest agreement | Declared table counts and digests must agree with the supplied records |

The local engine validates row counts and canonical table digests. The current Glue job validates
the batch ID, contract version, and row counts but does not yet bind every S3 object version and
checksum to the registered manifest. That managed-path gap must be closed before the data path can
be marked `AWS_VERIFIED`.

## Generation lifecycle

```text
registered -> building -> validated -> published
                       \-> failed
```

Every transformation writes a generation identifier. An incomplete or failed generation remains
physically inspectable but must not advance the active pointer. Recovery reuses the accepted batch
identity and deterministic generation. The AWS control plane still needs explicit lifecycle and
failure records beyond its current registered/published states.

## Financial reconciliation

- `line_total_cents = quantity * unit_price_cents` for every order line.
- `total_cents = subtotal_cents + tax_cents - discount_cents` for every order.
- The sum of line totals equals the order subtotal.
- Captured payments cover completed-order totals.
- Aggregate refunds do not exceed aggregate captured value.

Violations prevent publication.

## Returns

Every return references an existing order line, and cumulative returned quantity must not exceed
the ordered quantity. Refund validation is applied together with captured-payment validation.

## Inventory

Movements are ordered by event timestamp and movement ID for each product/store pair. Cumulative
stock must not become negative. This invariant is deterministic for equal timestamps because the
movement ID provides the tie-breaker.

## Bitemporal products

An order line resolves a product version by event time and by the version known at the manifest's
knowledge-time boundary. A missing version fails validation. The managed transformation still
needs an explicit exactly-one-match and overlapping-effective-interval check; existence alone is
not sufficient.

## Publication concurrency

Publication performs a DynamoDB transactional update guarded by the expected pointer version. One
publisher can advance a given pointer version; a stale writer fails without replacing the active
generation. The state machine must use the generation returned by batch registration rather than
trusting a separately supplied generation value. That binding is scheduled for correctness
hardening before the next AWS execution.

## Replay and recovery

A published batch returns replay success without creating a second logical generation. A failed
attempt may be rebuilt from the same immutable input. Recovery must not change the generation bound
to the original registration.

## Backfills

A backfill constructs an isolated generation. It has no serving effect until it passes the same
validation and publication conditions as a forward load.

## Serving boundary

DynamoDB is the current authority for the active-generation pointer. Athena is used for bounded
result validation, but the repository does not yet provide a complete analyst-facing resolver that
automatically scopes every query to that pointer. Until the resolver exists, raw Iceberg tables are
physical storage rather than the published serving contract.
