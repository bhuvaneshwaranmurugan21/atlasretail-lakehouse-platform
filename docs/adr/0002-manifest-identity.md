# ADR 0002: Treat the manifest digest as batch identity

- Status: Accepted
- Date: 2026-08-14

## Context

Object-store delivery is at least once. A filename or arrival timestamp cannot distinguish an
identical retry from a producer reusing an identifier for different content.

## Decision

The manifest contains the batch ID, contract version, knowledge-time boundary, row counts, logical
digests, and exact S3 key/version/size/ETag/SHA-256 evidence for all six datasets. DynamoDB stores
the first accepted manifest digest and exact manifest location for each batch ID. The same identity
is idempotent; a changed digest or manifest location is rejected.

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

The local implementation verifies canonical manifest identity. The Glue path reads the manifest by
version, checks registered object versions and checksums, and copies those exact versions into an
isolated read prefix. AWS run 33167646509 verified the managed exact-version path and rejected a new
S3 version whose bytes contradicted the registered object evidence.
