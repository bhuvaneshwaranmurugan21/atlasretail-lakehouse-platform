# ADR 0009: Preserve Part 4 closure through an immutable release

## Status

Accepted

## Context

Part 4 Stage 7 closed the project at commit
`9ec723e2fa9cf27c6bc486132fd44100e9d30443`. Its self-digesting receipt authenticates the sole
managed workload authority, cleanup-only recovery, final clean inventory, and the runtime-equivalent
107-file managed surface. GitHub workflow artifacts remain useful operational records, but their
configured retention is finite. A durable release must therefore depend on committed, sanitized,
digest-bound summaries rather than require expiring raw artifacts.

Adding release tooling under `aws`, `contracts`, `infra`, `scripts`, or `src` would change the frozen
runtime inventory. Changing the Stage 7 allowlist would also invalidate the committed closure
receipt. A release receipt also cannot contain the hash of the commit that contains that receipt,
because that creates a self-reference.

## Decision

Part 4 Stage 8 is repository-only release integrity, evidence preservation, and operational handoff.
Its controls live under `release/part4/stage8`, outside every frozen runtime root. CI continues to
recompute the Stage 7 107-file digest and rejects any runtime drift.

Stage 8 uses two reviewed changes. The controls change adds the strict schema, evidence-retention
catalog, deterministic receipt and archive tooling, adversarial tests, CI gates, and documentation.
After it merges, the evidence change publishes a release-readiness receipt bound to that known
controls commit. The receipt state is `READY_FOR_ANNOTATED_TAG`; it does not claim that a future tag
already exists.

After the evidence change merges, a fixed-header gzip archive is built twice from the exact final
commit and compared byte-for-byte. The annotated `v0.1.0` tag binds the final commit, committed
receipt file digest, and archive digest. A separate post-release verification record authenticates
the tag object and reproduced archive without adding a commit after the release target.

No signing key is configured. The tag therefore records `Signature-Claim: NOT_CLAIMED`; an
annotated tag and checksum provenance must not be represented as a cryptographic identity
signature.

## Claim boundary

Stage 8 is `LOCAL_VERIFIED` with `aws_execution: false`. The production claim remains false,
sustained operation remains unestablished, and actual billed cost remains `UNCLAIMED`. Stage 8 does
not dispatch an AWS workflow, refresh financial evidence, create infrastructure, repeat the managed
workload, or redefine any Stage 6 or Stage 7 authority.

## Failure behavior

Receipt mutation, unknown schema properties, missing or duplicate evidence authorities, dependence
on raw artifacts, path traversal, runtime drift, release-version drift, a lightweight tag, an
incorrect tag target, an annotation mismatch, or a non-reproducible archive fails closed. Published
tags are never moved; corrections require a new version and a superseding release.
