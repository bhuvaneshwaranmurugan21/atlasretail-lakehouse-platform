# ADR 0006: Immutable attempt-bound teardown authority

## Status

Accepted for AtlasRetail Part 4 Stage 5.

## Context

The bounded workflow needs a cleanup capability that survives execute-job failure without becoming
a general-purpose mutation path. A run ID alone is insufficient: GitHub retries have distinct run
attempts, source can change between runs, a Terraform plan may not match the deployed source, and
an expired lease must not silently authorize another operator. Teardown that trusts mutable job
state or a plain-text token cannot defensibly establish which infrastructure it may destroy.

## Decision

Construct one strict teardown-authority document only after the exact saved apply plan passes its
40-resource envelope validation and before that plan is applied. The authority binds:

- repository, owner, workflow, actor, `main` ref, event, run ID, run attempt and source commit;
- frozen contract, target, admission, source-tree and provenance digests;
- AWS account `857229544428`, region `ap-southeast-2`, OIDC role and backend coordinates;
- Terraform/provider/infrastructure digests and the saved plan JSON, binary and validation digests;
- the exact 40 managed and six read-only data addresses;
- order and cost bounds; and
- the account lease table, lock ID and attempt-bound owner.

The workflow independently recomputes the authority from original inputs, uploads it as an
immutable attempt-named artifact, and then conditionally changes the lease from `ACQUIRED` to
`AUTHORITY_BOUND` while recording the artifact identity and authority digest. Apply rehashes the
authority bytes and uses only the previously validated saved plan. It also records an apply outcome
receipt even when Terraform returns failure.

Normal teardown accepts only the exact authority bytes and an exact `AUTHORITY_BOUND` lease.
Deterministic recovery is a separate manual, `main`-only workflow. It runs trusted recovery code
against a separate checkout of the exact failed source, validates authority before requesting OIDC,
and assumes the teardown session intersection that denies workload starts and create/update
operations. Recovery may conditionally transition only the exact failed lease or conditionally
acquire an absent lease; it never overwrites a different owner and never uses expiry as takeover
authority. It creates and validates a destroy-only partial-state plan, hashes its binary, applies
only that saved plan, proves Terraform and AWS inventories clean, and releases only the exact
recovery lease after consistent-read absence proof.

## Consequences

- Missing, altered, cross-attempt, cross-source or cross-account authority fails before mutation.
- Artifact availability alone does not authorize teardown; the matching conditional lease state is
  also required.
- TTL remains storage hygiene, not ownership transfer. A stale conflicting lease requires an
  investigated operator decision rather than silent takeover.
- The recovery path cannot execute Glue, Step Functions, Lambda or Athena workloads and cannot
  create replacement infrastructure.
- A recovery artifact may claim `AWS_VERIFIED` only for exact cleanup when its inventory, budget and
  lease-release checks all pass. It does not promote workload correctness.
- Stage 5 implementation and CI evidence remain repository-only `LOCAL_VERIFIED` with
  `aws_execution: false`; no new managed run is claimed by this stage.
