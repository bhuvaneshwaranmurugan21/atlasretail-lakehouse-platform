# ADR 0008: Close Part 4 without re-claiming managed execution

## Status

Accepted

## Context

Part 4 Stage 6 already produced the complete managed workload authority. Run `33329861907`
passed all 20 frozen contract domains for source
`08559b0f48708080335282c6d59faa3826635d67`, and cleanup-only recovery run `33328391707`
resolved the failed predecessor without promoting its workload claim. Repeating the workload for
documentation closure would add cost and operational risk without establishing a missing technical
property.

Part 4 Stage 7 instead needs one durable, independently reproducible closure statement. That
statement must authenticate the committed Stage 6 summaries, prove that the managed runtime is
runtime-equivalent to the verified Stage 6 source, confirm a fresh clean AWS baseline, exclude raw
live identifiers, and preserve every existing claim boundary.

## Decision

Stage 7 uses two change sets. The first adds a strict closure schema, a frozen manifest for the 107
managed runtime files, an explicit allowlist for closure-only implementation files, deterministic
preflight sanitization and closure publication, adversarial tests, CI reproduction, and this
decision record. It also refreshes the short-lived owner-attested organization credit facts.

After the first change set merges, exactly one manual read-only preflight runs from `main`. It may
assume the repository's bounded read-only session, inspect the backend and account inventory, and
publish an artifact. It cannot apply or destroy Terraform, create AWS resources, or start Glue,
Step Functions, Athena, or Lambda workloads. The second change set commits only its sanitized
summary and manifest, the deterministic completion receipt, and final evidence references.

The Stage 7 completion receipt is repository-only `LOCAL_VERIFIED` evidence with
`aws_execution: false`. It references, but does not replace or promote, these independent
authorities:

- managed workload and finality: run `33329861907`, `AWS_VERIFIED`;
- deterministic cleanup-only recovery: run `33328391707`, `AWS_VERIFIED`;
- final clean inventory: the post-merge read-only preflight, `AWS_VERIFIED`.

The production claim remains false, actual billed cost remains `UNCLAIMED`, and sustained
operation is not established.

## Consequences

- Any byte change in the frozen managed runtime fails Stage 7 equivalence.
- Closure-only additions inside runtime roots must appear in the exact allowlist.
- Raw caller identity, resource identifiers, KMS identifiers, and detailed AWS responses stay out
  of Git; committed evidence contains counts, outcomes, attribution, and cryptographic digests.
- A stale owner attestation, non-main preflight, dirty Terraform state, active account lease,
  unexpected resource, KMS inspection error, digest mismatch, or inflated claim stops closure.
- Historical ADRs and incident records retain the facts and claim levels valid at their original
  time; Stage 7 adds context instead of rewriting them.

## Verification

CI rebuilds the runtime-equivalence and Stage 7 readiness receipts twice and compares their exact
bytes. Before the final preflight, the valid repository state contains neither final-preflight
evidence nor a completion receipt. Once a final-preflight manifest exists, CI requires exactly one
matching completion receipt and independently reconstructs it from the committed sources.
