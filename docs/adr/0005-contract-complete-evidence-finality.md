# ADR 0005: Contract-complete evidence and teardown finality

## Status

Accepted for AtlasRetail Part 4 Stage 4.

## Context

The bounded workflow previously summarized selected workload statuses before teardown and could
emit `AWS_VERIFIED` without proving every domain frozen by the Part 4 contract. A green data path
is not a complete run: exact source and session provenance, scenario semantics, saved plans,
deployed inventory, logs, metered usage, budget, teardown inventories, and account-lease finality
are all part of the result. Treating a conditional lease-delete failure as success also made an
ownership contradiction indistinguishable from clean release.

## Decision

Use two separate fail-closed authorities:

1. The execution checkpoint validates the exact eight Step Functions executions, six correlated
   Glue runs, semantic failure markers, replay behavior, deterministic recovery, active-pointer
   invariants, stale-writer rejection, generation-pinned Athena results, non-empty run-bound
   CloudWatch exports, deployment inventory, sessions, lease acquisition, metered usage, and the
   admitted budget. It records `AWS_EXECUTION_VALIDATED_PENDING_TEARDOWN` as state while retaining
   the contract claim level `UNCLAIMED`; it cannot emit `AWS_VERIFIED`.
2. The finalizer accepts only a passing checkpoint and then requires the validated saved
   destroy-only plan, complete AWS and Terraform absence proof, a target-bound teardown session,
   post-teardown budget evidence, and a conditional lease deletion followed by a consistent-read
   absence proof. Only this finalizer may emit `AWS_VERIFIED`.

The final artifact binds all 20 evidence domains and all 17 provenance fields in the frozen
contract. SHA-256 manifests cover the retained files. Unknown, missing, duplicated, unrelated, or
contradictory evidence fails the run. A failure receipt remains uploadable, but cannot promote a
claim. The legacy pre-teardown summarizer is retained only as a fail-closed rejection path.

Execution and teardown assume separate compact STS session intersections. Regional actions are
conditioned on `ap-southeast-2`; the organization-forbidden legacy region is never admitted.
Execution denies destructive
control-plane actions. Teardown denies workload starts. These intersections supplement, rather
than replace, exact admission, the live role policy, saved-plan validation, and semantic evidence.

## Consequences

- A successful workload with missing logs, failed teardown, residual Terraform/AWS inventory, or
  an unproved lease release is a failed Part 4 run.
- Replay cannot pass merely because Step Functions returned `SUCCEEDED`; the history must show no
  second Glue run.
- Expected failures require their exact contract signal, not a generic failed status.
- Recovery must retain the batch and generation identity and increase the attempt counter.
- Historical AWS artifacts remain attributed to their original commits. Stage 4 itself is
  repository-only `LOCAL_VERIFIED` readiness and performs no AWS operation.
- Actual settled billing, production scale, sustained operation, and SLA behavior remain
  `UNCLAIMED`.
