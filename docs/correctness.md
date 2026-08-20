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
| Object identity | Every managed file is bound to one S3 key, version, size, ETag, and SHA-256 |

The local engine validates row counts and canonical table digests. The managed job reads the
manifest by exact version, verifies its canonical digest, checks every registered object version
and checksum, and server-side copies that exact version into a generation-isolated read prefix.
These rules are locally verified; their Glue execution remains `DESIGNED` until the bounded run.

## Generation lifecycle

```text
registered -> building -> validated -> published
                       \-> failed
```

Registration deterministically derives the generation identifier from the batch and manifest
identity. Conditional DynamoDB transitions record attempts, execution identity, validation
evidence, failure stage, and normalized error. An incomplete generation may remain physically
inspectable but cannot advance the active pointer. Recovery reuses the accepted identity and
rewrites the same generation deterministically.

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
knowledge-time boundary. The match count must equal one. Both a missing interval and overlapping
knowable intervals fail validation; versions are never silently ranked to hide overlap.

## Publication concurrency

Publication performs a DynamoDB transactional update guarded by the expected pointer version and
the generation's `VALIDATED` state. One publisher can advance a given pointer version; a stale
writer fails without replacing the active generation. Every downstream state uses the generation
returned by registration rather than a caller-supplied identifier.

## Replay and recovery

A published batch returns replay success without creating a second logical generation. A failed
attempt may be rebuilt from the same immutable input. Recovery must not change the generation bound
to the original registration.

## Backfills

A backfill constructs an isolated generation. It has no serving effect until it passes the same
validation and publication conditions as a forward load.

## Serving boundary

DynamoDB is the authority for the active-generation pointer. The resolver reads that pointer once,
validates its published generation, and constructs a six-table query pinned to the same generation.
Raw Iceberg tables remain physical storage; enforcing resolver-only access requires production IAM
separation beyond this bounded environment.
