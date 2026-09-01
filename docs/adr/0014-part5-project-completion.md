# ADR 0014: Project completion requires final-main evidence and an annotated release tag

## Status

Accepted for Part 5 Stage 5 controls. Final completion remains pending until the controls merge,
the exact `main` CI run completes successfully, and the `v0.2.0` annotated tag is verified.

## Context

Part 5 Stages 1 through 4 establish the completion contract, traceability baseline, operational
handoff, and repository completion candidate. They deliberately leave `P5-GAP-001` and
`P5-GAP-002` open. A pull-request checkout cannot truthfully close either gap because it is not the
final merged source and its CI run does not prove the final `main` state.

The project also preserves strict claim boundaries. Part 5 Stage 5 performs no AWS operation. The
bounded Stage 6 authority remains the managed-workload proof; production readiness and sustained
operation are not claimed, and actual billed cost remains `UNCLAIMED`.

## Decision

Stage 5 separates readiness, project-completion attestation, and release verification:

1. Pull-request and in-progress `main` CI validate all predecessor authorities and emit only
   `FINAL_ATTESTATION_READY` with project completion false.
2. The exact merged commit must pass four named jobs: `correctness`,
   `glue-runtime-integration`, `terraform`, and `project-completion-readiness`.
3. An external receipt builder accepts only a completed successful `push` run for `main` whose
   head SHA equals the checked-out final commit. Missing, skipped, extra, or failed jobs are
   rejected.
4. Only that receipt may reach `PROJECT_COMPLETION_VERIFIED`, close all six Part 5 gaps, and set
   project completion true.
5. The `v0.2.0` release uses an annotated tag. Its annotation binds the final commit, final-main CI
   run ID, completion-receipt SHA-256, deterministic source-archive SHA-256, Stage 4 receipt
   SHA-256, and the explicit `NOT_CLAIMED` signature boundary.
6. A post-completion verifier requires an annotated tag object, exact receipt/tag/commit binding,
   and byte-for-byte reproduction of the fixed-header gzip source archive.

The completion receipt is external to the final commit because committing it would create a newer
source commit and invalidate its own final-source assertion. The receipt, archive, checksums, and
post-completion verification record are GitHub release assets.

## Consequences

- The Stage 5 repository pull request cannot claim completion.
- The last two gaps close together only after exact final-main evidence exists.
- No evidence-only commit follows the final source commit.
- Lightweight tags, mutable tag targets, altered archives, incomplete CI, or post-attestation
  commits fail verification.
- The release is reproducible and auditable without inflating AWS, production, sustained-operation,
  signature, or settled-billing claims.
