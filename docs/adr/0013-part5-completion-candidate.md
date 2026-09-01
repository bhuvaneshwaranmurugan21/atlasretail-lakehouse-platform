# ADR 0013: Part 5 completion-candidate audit

## Status

Accepted

## Context

The Part 5 Stage 2 baseline left repository naming, source-exact quality gates, and critical-defect
closure open. Stage 3 closed the operational-handoff gap without changing those repository-quality
gaps. Closing any one of the three in isolation would create a misleading candidate: the naming
scan is meaningful only on the same source that passed the complete quality and defect audit.

## Decision

Part 5 Stage 4 closes `P5-GAP-004`, `P5-GAP-005`, and `P5-GAP-006` as one indivisible
completion-candidate audit. The candidate:

1. Scans every candidate tracked path, every UTF-8 tracked file, and every post-policy commit
   subject for prohibited project branding.
2. Binds sixteen source-exact quality checks enforced by the successful controls-merge `main` CI
   run, including lint, format, strict typing, coverage, deterministic controls, CloudFormation,
   Glue-compatible integration, sensitive-material scanning, and Terraform validation.
3. Audits twelve defect domains with explicit evidence mappings and rejects absent domains,
   unresolved critical findings, unresolved high findings, or attempts to classify either severity
   as an accepted limitation.
4. Preserves the Stage 3 authority, frozen 107-file runtime, release authority, and conservative
   claim boundaries.
5. Records the predecessor, newly closed, and remaining gap sets separately and proves that they
   partition the complete Stage 2 six-gap baseline exactly once.

Controls reach `COMPLETION_CANDIDATE_CONTROLS_READY`. The final receipt reaches
`COMPLETION_CANDIDATE_VERIFIED` only after it binds the controls merge and its successful `main` CI
run in a separate evidence-only change.

## Consequences

Stage 4 is repository-only and performs no AWS operation. `P5-GAP-001` and `P5-GAP-002` remain
blocking, all Part 5 stages are not yet complete, and project completion remains false. Production
remains `NOT_CLAIMED`, sustained operation remains `NOT_ESTABLISHED`, and actual billed cost
remains `UNCLAIMED`.

The historical repository is not rewritten because doing so would invalidate the published
`v0.1.0` tag and its checksum provenance. The naming claim covers the completion-candidate tree and
commit subjects created after the policy boundary.

If any required command, audit domain, authority, or claim boundary fails, Stage 4 stops. The root
cause must be corrected and the complete audit rerun; deleting a check, reducing coverage, or
reclassifying a critical or high finding is not an acceptable resolution.
