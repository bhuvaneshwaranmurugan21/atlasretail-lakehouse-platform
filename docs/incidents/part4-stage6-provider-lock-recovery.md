# Part 4 Stage 6 provider-lock recovery

## Status

Resolved. No active AtlasRetail workload resources or account lease remain.

## Impact

Bounded run [33326519783](https://github.com/bhuvaneshwaranmurugan21/atlasretail-lakehouse-platform/actions/runs/33326519783)
completed admission, the 40-resource apply, all managed workload scenarios, Athena validation, and
the execution evidence checkpoint. Automatic teardown then stopped before creating a destroy plan
because a fresh job did not reproduce the runtime-generated, untracked Terraform provider lock.
The run correctly remained failed with its final claim `UNCLAIMED`.

No correctness requirement was bypassed. The exact authority-bound lease remained in place so only
the cleanup path for that run could act on the state.

## Root cause and correction

The teardown authority bound the provider lock produced by Terraform 1.11.4 during the execution
job. A fresh teardown or recovery checkout compared that authority with its pre-initialization lock
bytes, so the independent byte-strict validator rejected the mismatch.

Recovery run [33327855730](https://github.com/bhuvaneshwaranmurugan21/atlasretail-lakehouse-platform/actions/runs/33327855730)
reproduced the mismatch before AWS credentials were requested. It performed no lease transfer,
destroy, workload, or infrastructure mutation.

[Pull request 76](https://github.com/bhuvaneshwaranmurugan21/atlasretail-lakehouse-platform/pull/76)
made both cleanup paths run Terraform 1.11.4 initialization with `-backend=false` on the exact
source before authority validation. This deterministically materializes the provider lock without
AWS credentials or backend access. The byte-strict authority validator and every authority binding
remained unchanged.

## Recovery proof

Cleanup-only recovery run [33328391707](https://github.com/bhuvaneshwaranmurugan21/atlasretail-lakehouse-platform/actions/runs/33328391707)
validated the original run, attempt, source, authority, plan envelope, target, backend, and lease;
transferred only that exact authority-bound lease; validated and applied the 40-resource destroy
plan; passed all 20 cleanup checks; proved the budget bound; and conditionally released the
recovery-bound lease. Independent preflight
[33328532420](https://github.com/bhuvaneshwaranmurugan21/atlasretail-lakehouse-platform/actions/runs/33328532420)
then proved the lease absent, Terraform state empty, and no unexpected active resources.

The recovery evidence is cleanup-only `AWS_VERIFIED`. It does not promote the failed run's workload
checkpoint or failed final summary.

## Final Stage 6 proof

The complete current-source prerequisite chain and bounded run were repeated after the correction:

- read-only preflight `33328532420`
- Glue create/delete capability probe `33329607444`
- exact plan-only proof `33329689861`
- bounded managed execution and teardown `33329861907`
- independent post-teardown preflight `33331233341`

Run `33329861907` completed all 20 contract domains and emitted the sole finalizer's
`AWS_VERIFIED` result only after its exact destroy plan, clean inventories, budget proof, and lease
release passed. Preflight `33331233341` independently confirmed the final clean state.
