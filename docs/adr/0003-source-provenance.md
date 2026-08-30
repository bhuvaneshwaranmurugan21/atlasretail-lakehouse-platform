# ADR 0003: Separate logical, object-byte, and execution provenance identities

## Status

Accepted for AtlasRetail Part 4 Stage 2.

## Context

The existing generator was logically deterministic: the same parameters produced the same retail
records and table digests. Its gzip writer nevertheless embedded the wall-clock time, so identical
records could produce different S3 object bytes. The managed manifest also describes exact S3
versions, which do not exist while a source bundle is still local. Treating any one of these
identities as a substitute for the others would make replay, object-tamper, and recovery evidence
ambiguous.

## Decision

AtlasRetail records three separate identities:

1. Canonical business-record digests identify logical table content.
2. SHA-256 digests of deterministic gzip members identify exact source object bytes.
3. A provenance receipt identifies the source commit, frozen execution contract, target, scenario
   catalogue, source and managed manifest schemas, generator parameters, and runtime versions.

The source manifest schema requires empty object-version arrays. The managed `retail-v2` schema
requires at least one exact S3 object identity per table. Upload is the explicit boundary between
those states. The gzip encoder fixes compression level, timestamp, filename, and OS header fields.
Failure and recovery share one physical source, replay reuses the exact success registration, and
the tamper proof has a separate mutation receipt.

## Consequences

- Identical source specifications can be compared byte-for-byte across independent processes.
- A changed source commit changes execution provenance without redefining business-content identity.
- A recompressed or mutated object is distinguishable from an identical logical dataset.
- Source bundles cannot claim managed S3 identity before upload.
- Schema, catalogue, parameter, byte, receipt, and scenario-relationship drift fail closed.
- Stage 2 evidence remains `LOCAL_VERIFIED`; these controls alone make no AWS or production claim.
