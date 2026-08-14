# ADR 0002: Treat the manifest digest as batch identity

- Status: Accepted
- Date: 2026-08-14

## Context

Object-store delivery is at least once. A filename alone cannot distinguish a safe replay from a
producer reusing an ID for different content.

## Decision

The manifest contains row counts and canonical SHA-256 digests for all six tables. DynamoDB stores
the first accepted identity digest for each batch ID. The same pair is idempotent; the same ID with
a different digest is a conflict.

## Consequences

Retries are safe and conflicting upstream behaviour is visible. Producers must generate a stable
canonical representation and cannot mutate an accepted batch in place.
