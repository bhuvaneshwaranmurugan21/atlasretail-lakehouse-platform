# AtlasRetail partial-apply incident: 2026-08-14

## Status

Remediation prepared. The rescue workflow must not be dispatched until its code is merged,
the corrected inline policy is attached to the AtlasRetail GitHub OIDC role, and an
identity-only OIDC test succeeds.

## Scope

- Failed workflow: `AWS bounded lab`
- GitHub run: [31791499897](https://github.com/bhuvaneshwaranmurugan21/atlasretail-lakehouse-platform/actions/runs/31791499897)
- Source commit: `e1772d27ab77e81cb2cb2f5c6dac2f8a339178e5`
- AWS account: `887720497919`
- AWS region: `ap-south-1`
- Terraform backend key: `atlasretail/main.tfstate`

No workload proof ran. Glue execution, Step Functions success/replay/failure/recovery,
Athena verification, runtime measurement, and cost measurement were all skipped because
Terraform apply failed.

## What happened

Terraform partially created the lab before provider calls encountered three IAM contract
gaps:

1. `kms:CreateGrant` was absent, blocking the DynamoDB table encrypted by the lab KMS key.
2. `logs:DescribeLogGroups` was placed in a resource-scoped statement although the list API
   requires account-wide resource scope.
3. `s3:GetReplicationConfiguration` was absent, so provider refresh failed for all three
   S3 buckets during cleanup.

The unconditional cleanup step ran, but Terraform could not complete its refresh and destroy.
The teardown verifier then correctly failed because Terraform state and the RunId tag
inventory still contained resources. Review also found that the verifier treated a tagged
KMS key as acceptable without proving that AWS had placed it in `PendingDeletion`; that was
an unsafe false-pass path.

## Remediation

- Add the missing S3 provider read.
- move `logs:DescribeLogGroups` to an explicit `Resource: "*"` statement.
- allow KMS service grants only when `kms:GrantIsForAWSResource` is true.
- add the Glue catalog reads required by the Athena verification path.
- expose deterministic resource names as Terraform outputs.
- verify each named resource class, recursively inspect Terraform state, and inspect the
  RunId tag inventory.
- allow the KMS key only after `DescribeKey` proves `PendingDeletion` and provides a
  deletion date; separately prove that its alias is absent.
- add an incident-specific rescue workflow that can only create and apply a saved
  `terraform plan -destroy` for run `31791499897`.

## Rescue procedure

1. Merge the remediation through a reviewed pull request with green CI.
2. Replace the AtlasRetail OIDC role's inline policy with the repository policy document.
3. Run the identity-only OIDC workflow and require a pass.
4. Obtain action-time confirmation for destructive cleanup.
5. Dispatch `AWS rescue teardown` with the incident defaults and type `DESTROY`.
6. Download and retain the rescue evidence artifact.
7. Require every teardown check to pass before running another bounded lab.

## Acceptance criteria

- The destroy-only plan targets the incident state and contains no create or update action.
- Its saved plan applies successfully.
- All three S3 buckets return explicit not-found results.
- DynamoDB, Glue job/database, Athena workgroup, Lambda, Step Functions, IAM roles,
  CloudWatch log groups/alarm, and the KMS alias are explicitly absent.
- The KMS key is demonstrably `PendingDeletion` with a deletion date.
- Terraform state is readable and recursively empty.
- The RunId tag inventory contains no resource except that proven pending-deletion KMS key.
- The account lease is released and the evidence artifact is uploaded even if cleanup fails.

Only after these criteria pass may a new bounded AtlasRetail execution begin.
