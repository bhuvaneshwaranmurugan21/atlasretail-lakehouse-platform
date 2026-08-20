# AtlasRetail partial-apply incident: 2026-08-14

## Status

Resolved. The original Terraform state was removed, the residual Glue authorization scope was
corrected, and a subsequent read-only preflight established a clean backend before another
deployment was authorized.

## Scope

- Failed workflow: `AWS bounded lab`
- GitHub run: [31791499897](https://github.com/bhuvaneshwaranmurugan21/atlasretail-lakehouse-platform/actions/runs/31791499897)
- Source commit: `e1772d27ab77e81cb2cb2f5c6dac2f8a339178e5`
- AWS account: `887720497919`
- AWS region: `ap-south-1`
- Terraform backend key: `atlasretail/main.tfstate`

No data-processing workload ran. Glue execution, Step Functions scenarios, Athena validation,
runtime measurement, and workload-cost measurement were skipped because Terraform apply failed.

## Impact

Terraform partially created the validation environment. Normal cleanup could not refresh every
resource, so Terraform state and run-tag inventory remained non-empty. The account lease was
released, but another Atlas deployment was blocked until exact-state recovery and independent
absence checks succeeded.

## Root cause

Three IAM contract gaps appeared during provider operations:

1. `kms:CreateGrant` was absent for the DynamoDB service grant.
2. `logs:DescribeLogGroups` was incorrectly placed in a resource-scoped statement.
3. `s3:GetReplicationConfiguration` was absent from the provider refresh permissions.

Review also found an unsafe verifier boundary: a tagged KMS key could have been accepted without
proving `PendingDeletion` and recording its deletion date.

## Corrections

- Added the required S3 provider read.
- Moved global CloudWatch Logs discovery to `Resource: "*"`.
- Allowed KMS service grants only when `kms:GrantIsForAWSResource` is true.
- Added the Glue catalog reads required by the Athena path.
- Exposed deterministic resource names as Terraform outputs.
- Required explicit checks for every named resource, recursive Terraform state, and run-tag
  inventory.
- Required a pending-deletion state and deletion date for the KMS exception.
- Added an exact-run rescue workflow restricted to a saved destroy-only plan.

## Rescue history

The first rescue was [run 31794022586](https://github.com/bhuvaneshwaranmurugan21/atlasretail-lakehouse-platform/actions/runs/31794022586).
Its saved destroy plan removed the three S3 buckets, three IAM roles, three log groups, KMS alias,
and random suffix from state, and scheduled the KMS key for deletion. The account lease was
released. The artifact digest was
`sha256:244f703e6c66a34805fa16af153d679cf43cb1edb69d97bdb875950ad3a2a1ab`.

Glue rejected database deletion because authorization also evaluated the database's
`userDefinedFunction` descendants. The policy was restricted to the AtlasRetail UDF namespace,
the residual database was removed in the corrected recovery path, and later preflight checks
confirmed that the backend and tagged inventory were clean.

## Verification criteria

- The saved recovery plan contained destroy actions only.
- S3, DynamoDB, Glue, Athena, Lambda, Step Functions, IAM, CloudWatch, and the KMS alias were absent.
- The KMS key was in `PendingDeletion` with a recorded date.
- Terraform state was readable and recursively empty.
- Run-tag inventory contained no unexpected resource.
- The account lease was released.

The checked-in incident output manifest preserves resource identifiers that could no longer be
recovered after partial Terraform state removal.
