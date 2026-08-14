# AWS lab runbook

## Safety preconditions

1. Use account `887720497919` in `ap-south-1`.
2. Keep the role trust restricted to this repository's `main` branch.
3. Attach only the generated AtlasRetail deployment policy.
4. Confirm the shared budget and account lock exist.
5. Use a unique run ID and the default small workload first.

## Execute

Run the `AWS bounded lab` workflow from GitHub Actions. Keep `order_count` at 1,000 until the
baseline completes. The workflow acquires an account lock, proves the remote state and tagged
inventory are clean, machine-validates a saved create-only Terraform plan, uploads deterministic
input, runs the success and injected-failure scenarios, and collects evidence. An independent job
then validates and applies a saved destroy-only plan.

## Expected signals

- The success execution ends `SUCCEEDED` and publishes one new pointer version.
- The injected failure ends `FAILED`; the active generation and pointer version do not change.
- Replaying the success batch does not create a second logical generation.
- Athena orders and gross value exactly match the deterministic expected-results contract.
- CloudWatch event exports, Step Functions histories, Athena query statistics, Terraform plans and
  outputs, resource inventory, runtime, and estimated cost appear in the workflow artifact.

## Recovery

If transformation fails, inspect the Glue driver log and the quarantined manifest. Correct the data
or code, then replay the same immutable manifest. Never manually move the active pointer around a
failed gate.

## Teardown verification

Before apply, the execution job persists an immutable teardown-authority marker. The independent
teardown job runs even when the execution job fails or times out, but it will destroy state only
when that marker belongs to the same repository run. It creates, validates, and applies a saved
destroy-only plan. It then checks every named resource from the Terraform outputs, confirms that
Terraform state is readable and empty, and inventories resources carrying the workflow's `RunId`
tag. Only explicit service-specific not-found responses prove deletion; authorization or API
errors fail closed. A KMS key awaiting AWS's mandatory scheduled-deletion window is the only
documented exception. The workflow writes `teardown.json`, and a failed cleanup is a failed lab
even when the data path passed.
