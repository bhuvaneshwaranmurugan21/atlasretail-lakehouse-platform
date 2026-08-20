# ADR 0002: Treat the manifest digest as batch identity

- Status: Accepted
- Date: 2026-08-14

## Context

Object-store delivery is at least once. A filename or arrival timestamp cannot distinguish an
identical retry from a producer reusing an identifier for different content.

## Decision

The manifest contains the batch ID, contract version, knowledge-time boundary, row counts, and
canonical SHA-256 digests for all six datasets. DynamoDB stores the first accepted manifest digest
for each batch ID. The same ID and digest is an idempotent delivery; the same ID with another digest
is rejected.

## Alternatives considered

### Use the object key as identity

Rejected because an object can be replaced or versioned under the same key.

### Use the ingestion timestamp as identity

Rejected because a replay receives a different timestamp and creates a second business effect.

### Bind the business batch ID to canonical content

Selected because the producer-visible identifier remains stable while content reuse becomes an
explicit conflict.

## Consequences

- Producers must produce a stable canonical representation.
- Replays are cheap after publication.
- Conflicting upstream behaviour is visible and attributable.
- Manifest construction and verification become part of the trusted ingestion boundary.

## Current boundary

The local implementation recalculates table digests. The Glue path currently validates identity
fields and row counts but does not yet verify exact S3 object versions and checksums. Managed input
immutability therefore remains incomplete until that validation is added.
