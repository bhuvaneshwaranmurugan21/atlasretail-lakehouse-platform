# AWS lab runbook

## Safety preconditions

1. Use account `887720497919` in `ap-south-1`.
2. Keep the role trust restricted to this repository's `main` branch.
3. Attach only the generated AtlasRetail deployment policy.
4. Confirm the shared budget and account lock exist.
5. Use a unique run ID and the default small workload first.

## Execute

Run the `AWS bounded lab` workflow from GitHub Actions. Keep `order_count` at 1,000 until the
baseline completes. The workflow acquires an account lock, applies Terraform, uploads deterministic
input, runs the success and injected-failure scenarios, collects evidence, and tears down.

## Expected signals

- The success execution ends `SUCCEEDED` and publishes one new pointer version.
- The injected failure ends `FAILED`; the active generation and pointer version do not change.
- Replaying the success batch does not create a second logical generation.
- CloudWatch log exports, Step Functions histories, Athena query statistics, Terraform outputs,
  resource inventory, runtime, and estimated cost appear in the workflow artifact.

## Recovery

If transformation fails, inspect the Glue driver log and the quarantined manifest. Correct the data
or code, then replay the same immutable manifest. Never manually move the active pointer around a
failed gate.

## Teardown verification

The workflow always executes `terraform destroy`. It then checks every named resource from the
Terraform outputs, confirms that Terraform state is readable and empty, and inventories resources
carrying the workflow's `RunId` tag. Only explicit service-specific not-found responses prove
deletion; authorization or API errors fail closed. A KMS key awaiting AWS's mandatory
scheduled-deletion window is the only documented exception. The workflow writes `teardown.json`,
and a failed cleanup is a failed lab even when the data path passed.
