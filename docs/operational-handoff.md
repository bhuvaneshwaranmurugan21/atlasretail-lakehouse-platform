# AtlasRetail operational handoff

This handoff covers repository-verified operation, recovery, and escalation decisions for the
bounded AtlasRetail validation environment. It does not authorize a production deployment or an
unreviewed AWS run.

## Authority order

Use authorities in this order:

1. The annotated `v0.1.0` release and Part 4 Stage 8 receipt.
2. The Part 4 Stage 7 closure receipt and frozen 107-file runtime manifest.
3. The Part 5 Stage 1 completion contract.
4. The Part 5 Stage 2 completion-gap baseline.
5. The current trusted `main` runbook and workflow definitions.
6. Exact run, attempt, source, target, lease, plan, and teardown evidence for an individual run.

An expiring workflow artifact is not required for a durable claim when its committed summary and
digest authority are present. Credentials, caller identities, raw logs, and live resource
identifiers must not be committed.

## Normal operation

Before considering the bounded workflow:

1. Require the exact current `main` source and checked-in AWS target.
2. Require a successful source-exact read-only preflight.
3. Require a successful definition-only Glue capability probe and independent cleanup.
4. Require a successful source-exact plan-only proof.
5. Provide those three exact run IDs to `AWS bounded lab`.
6. Preserve the order, cost, execution, and teardown confirmations.
7. Require contract-complete final evidence, exact teardown, clean inventory, and lease release.

Do not dispatch from another ref, reuse stale prerequisite evidence, proceed from unreadable or
non-empty state, or execute without teardown confirmation.

## Authority-bound recovery

Use `AWS bounded lab recovery` only when the failed attempt persisted immutable teardown
authority. Supply the exact failed run, run attempt, and source commit. The workflow must validate
the original authority, target, backend, plan envelope, and lease before AWS access; create and
apply only the validated destroy-only plan; prove clean inventory; and release only the exact
recovery-bound lease.

The provider-lock incident for failed run `33326519783` and cleanup-only recovery run
`33328391707` is the reference authority. The failed run remains `UNCLAIMED`. Recovery proves
cleanup only and cannot promote the failed workload checkpoint into a correctness claim.

Never delete resources manually, edit the lease, substitute another run's authority, or issue a
fresh unbound destroy command.

## Lease-only recovery

Use `AWS bounded lab lease recovery` only when the exact failed run acquired the account lease but
failed before immutable teardown authority existed. The path requires:

- exact failed run, attempt, source, and admitted target;
- an exact live `ACQUIRED` lease with no teardown authority;
- readable and empty Terraform state; and
- empty AWS resource inventory.

If state or resources exist, stop. The lease-only path must neither release the lease nor perform
infrastructure cleanup. Never rely on expiry to take over a lease.

## Stop and escalate

Stop and escalate rather than retry automatically when any of these conditions occurs:

- account-plan or service-access denial;
- IAM authorization failure;
- unreadable or non-empty Terraform state;
- unexpected tagged resources;
- manifest or business-invariant failure;
- missing service history, evidence, or teardown authority;
- ambiguous lease ownership;
- source, digest, target, or plan disagreement; or
- failed or skipped teardown.

Preserve repository, source, run, attempt, target, failed step, error classification, lease state,
Terraform state, resource inventory, teardown authority, and evidence digests. Classify the
result as stop, recover, investigate, or reject evidence. Correct one root cause, pass repository
validation, and require a new read-only preflight before another deployment decision.

Historical denial and partial-apply incidents are forensic authorities for their original
environment. Their exact targets remain preserved only in the immutable incident evidence; they
do not describe the repository's current validated target.

## Stage 3 verification boundary

Part 5 Stage 3 rehearses normal operation, authority-bound recovery, lease-only recovery, and stop
and escalate without an AWS operation. Controls reach `HANDOFF_CONTROLS_READY`; the separate
receipt reaches `OPERATIONAL_HANDOFF_VERIFIED` only after it binds the controls merge and successful
`main` CI.

Only `P5-GAP-003` is closed. Five later completion gaps remain blocking, project completion remains false,
the production claim remains false, sustained operation remains unestablished, and actual billed
cost remains `UNCLAIMED`.
