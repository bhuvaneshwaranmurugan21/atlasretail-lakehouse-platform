# ADR 0007: Bind managed execution to current-source prerequisites

## Status

Accepted

## Context

The bounded workload workflow could admit its operator, source tree, run attempt, confirmations,
cost limit, and workload size without proving that the same source commit had passed the required
read-only account preflight, Glue create/delete capability probe, and exact plan-only proof. The
workflow also needed explicit controls for destroy-plan binary integrity, shell syntax, credential
lifetime, final failure evidence, and a lease stranded before teardown authority existed.

These are semantic admission and recovery changes. The Part 4 contract therefore advances from
version 1.0.0 to 1.1.0, invalidating prerequisites produced for an earlier source or contract.

## Decision

The bounded workflow accepts three exact prerequisite run IDs. A no-OIDC admission job downloads
their immutable artifacts, validates their source, target, clean-state, capability, cleanup, and
40-managed/six-read-only plan envelopes, hashes every artifact file, and emits a self-digesting
receipt. The ordinary run admission binds that receipt and its three run IDs. Every later admission
revalidation requires the same prerequisite receipt.

The execute job is limited to 55 minutes with an explicit 3,600-second role session. The normal
destroy path records the binary, JSON, and validation digests and rechecks all three immediately
before applying the saved binary plan. Final evidence uses the binary destroy-plan digest.

A separate manual, main-only lease-recovery workflow may release a lease in `ACQUIRED` state only
after it validates the failed admission and lease artifact, proves empty Terraform and AWS
inventories, consistently reads the exact live lease with no authority, and conditionally deletes
that exact owner/attempt/source/contract/target/state record. It cannot apply Terraform, create
resources, start workloads, or take over an expired lease.

CI syntax-checks every embedded workflow shell program and produces a deterministic Stage 6
readiness receipt twice. The readiness receipt remains `LOCAL_VERIFIED` and cannot assert that AWS
execution occurred.

## Consequences

- Any source or contract change requires fresh preflight, Glue probe, and plan-only run IDs.
- A rerun attempt cannot reuse admission from another attempt.
- Pre-authority and post-authority failures use distinct recovery paths.
- A missing runtime file still results in a structured failing final summary and uploaded evidence.
- The final `AWS_VERIFIED` claim remains unavailable until the bounded run, teardown, lease release,
  and independent post-teardown verification all pass.

## Verification

Source `08559b0f48708080335282c6d59faa3826635d67` passed the required preflight, Glue capability,
and exact plan-only prerequisites in runs `33328532420`, `33329607444`, and `33329689861`.
Bounded run `33329861907` then passed all 20 contract domains, exact-state teardown, budget finality,
and lease release before emitting `AWS_VERIFIED`. Independent preflight `33331233341` confirmed
empty Terraform state, an absent lease, and no unexpected active resources after the run.

The preceding attempt `33326519783` remains failed and `UNCLAIMED`: its workload checkpoint passed,
but automatic teardown could not reproduce the provider lock file. Cleanup-only recovery run
`33328391707` used the exact failed-run authority, destroyed the 40-resource partial state, passed
all 20 cleanup checks, and released the lease without promoting the failed workload claim.
