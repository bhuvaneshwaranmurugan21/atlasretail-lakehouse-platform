# Glue service-access denial: 2026-08-14

## Status

Infrastructure recovered; managed workload blocked. The failed run's resources were removed and
independently verified. A new data-processing run requires an AWS account plan that permits Glue
job creation and closure of the correctness boundaries listed in `docs/correctness.md`.

## Scope

- Failed workflow: `AWS bounded lab`
- GitHub run: [31810378794](https://github.com/bhuvaneshwaranmurugan21/atlasretail-lakehouse-platform/actions/runs/31810378794)
- Source commit: `0665a4b85dc498327bd48f288fe6f430a113abf8`
- AWS account: `887720497919`
- AWS region: `ap-south-1`
- Terraform backend key: `atlasretail/main.tfstate`

## What happened

The saved Terraform apply plan passed its resource and action checks. Apply created part of the
ephemeral environment and then AWS denied `glue:CreateJob` at the account-plan boundary. This was
not a missing resource ARN in the role policy: the AWS Free plan did not permit the service action
for the account.

Because apply stopped before the workflow's data stage:

- Synthetic inputs were not uploaded.
- No Glue job ran.
- No Step Functions success, replay, failure, or recovery execution ran.
- No Iceberg generation was created.
- No Athena business query ran.
- No workload runtime, throughput, scan, or cost result was produced.

Automatic teardown then encountered a separate read-only permission gap:
`states:ValidateStateMachineDefinition` was absent. The role was corrected with that action at
`Resource: "*"`, and the repository policy was reconciled to the same definition.

## Recovery

Recovery was prepared and merged through
[PR 16](https://github.com/bhuvaneshwaranmurugan21/atlasretail-lakehouse-platform/pull/16).
[Run 31812211040](https://github.com/bhuvaneshwaranmurugan21/atlasretail-lakehouse-platform/actions/runs/31812211040)
validated the exact backend and incident authority, created a saved destroy-only plan, applied it,
and ran independent service checks.

## Result

- Terraform reported `0 added, 0 changed, 37 destroyed`.
- Twenty independent cleanup checks reported deletion.
- All three S3 buckets and the named DynamoDB, Glue, Athena, Lambda, Step Functions, IAM,
  CloudWatch, and KMS alias resources were absent.
- Terraform state was readable and empty.
- Run-tag inventory contained no unexpected resource.
- The KMS key was in AWS-mandated `PendingDeletion` with a deletion date.
- The account-wide lease was released.
- Evidence artifact digest:
  `sha256:426f298c8b6e120ff6180010041c3a0284d0a598b20b6d69f637126696e5e14d`.

## Follow-up

Do not redesign or rerun the workflow merely to bypass the account-plan denial. First close the
managed-path correctness boundaries, then make an explicit account-plan and cost decision. A new
run must begin with identity verification, a clean read-only preflight, and a separately reviewed
authorization.
