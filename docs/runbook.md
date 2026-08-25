# AWS validation runbook

## Current stop condition

Do not dispatch the data-processing workflow unless the read-only preflight records an AWS account
plan of `PAID` and `ACTIVE` with remaining USD credits at or above the bounded run's cost ceiling,
and the definition-only Glue capability probe creates and deletes its temporary job successfully.
The probe must report zero Glue job runs and independently verify cleanup. A visible Glue console
or available CloudShell session is not evidence of `glue:CreateJob` authorization. The previous
denial stopped during Terraform apply; no Glue, Step Functions, or Athena workload executed.

## Preconditions

1. Use account `887720497919` and region `ap-south-1`.
2. Keep the GitHub OIDC trust restricted to this repository's `main` branch.
3. Confirm that the deployed inline policy matches
   `infra/iam/atlasretail-github-role-policy.json`.
4. Require a successful identity-only workflow and read-only environment preflight.
5. Require `freetier:GetAccountPlanState` to return `PAID` and `ACTIVE`, and preserve the response
   plus the fail-closed verification result in the preflight evidence artifact.
6. Run the definition-only Glue service probe and require successful creation, deletion,
   independently verified cleanup, and zero job runs.
7. Confirm that `atlasretail/main.tfstate` is readable and empty.
8. Confirm that the shared budget and account lease exist.
9. Use a unique run ID and begin with 500 synthetic orders.
10. Review the open correctness boundaries in `docs/correctness.md` before authorizing execution.

## Plan-only approval gate

The `AWS plan-only proof` workflow runs before any deployment authorization. It:

1. Obtains short-lived credentials through the repository-and-branch-bound OIDC role.
2. Verifies the paid account state, remaining credits, monthly budget, current spend, and a
   five-dollar gross run ceiling.
3. Compares the live inline role policy with the checked-in policy and rejects managed-policy
   attachments or broader OIDC trust.
4. Reads the locked remote backend and proves that state and tagged inventory are clean.
5. Generates a fresh plan for the exact `main` commit and rejects updates, replacements, deletions,
   unexpected resource types, or counts beyond the checked-in envelope.
6. Validates the planned managed lifecycle definition with the Step Functions API.
7. Repeats the state and inventory checks and proves that the planning operation created no
   persistent AtlasRetail infrastructure.
8. Publishes only sanitized inventory, validation results, source identity, and content hashes;
   the binary plan is never published or reused for deployment.

A later deployment must regenerate its own saved plan and compare it with the approved resource
envelope. A plan-only artifact is evidence for review, not deployment authority.

## Deploy and execute

Run `AWS bounded lab` manually with `order_count=500` and `confirm_destroy=DESTROY`. The workflow:

1. Validates the account, region, inputs, and source authorization.
2. Acquires the account-wide DynamoDB lease.
3. Initializes the locked remote Terraform state.
4. Proves that state and tagged inventory are clean.
5. Persists teardown authority before infrastructure creation.
6. Creates and machine-validates a saved create-only plan and validates the planned ASL definition
   through the Step Functions API.
7. Applies only that saved plan.
8. Uploads deterministic inputs with exact S3 version and checksum evidence.
9. Runs success, replay, batch-conflict, object-tamper, injected-failure, recovery, temporal-overlap,
   financial-mismatch, and stale-publisher scenarios.
10. Resolves one published generation and executes bounded Athena validation across all six tables.
11. Captures service histories, logs, metrics, plans, outputs, runtime, and immediate cost estimates.
12. Invokes the independent teardown job regardless of execution outcome.

## Expected signals

- Successful transformation and publication end `SUCCEEDED`.
- Identical replay does not create a second logical generation.
- Injected failure ends `FAILED` and does not move the active pointer.
- Recovery ends `SUCCEEDED` for the accepted batch identity.
- Batch conflict, object tamper, temporal overlap, and financial mismatch end `FAILED` before
  publication.
- The control-plane stale publisher fails without replacing the resolved generation.
- Athena row count and gross value match the deterministic expected-results contract.
- The evidence summary and teardown report both return `PASS`.

## Stop conditions

Do not retry automatically when any of the following occurs:

- Account-plan or service-access denial
- IAM authorization failure
- Terraform state or tagged-resource residue
- Manifest or business-validation failure
- Missing service history or evidence file
- Failed or skipped teardown check

Classify the failure, preserve the run and source identifiers, correct one root cause, validate the
change locally and in CI, and run a new read-only preflight before another deployment.

## Recovery

For transformation failures, inspect the Glue driver log, Step Functions history, registered batch
record, and immutable input identity. Correct data or code without changing the accepted batch
identity. Do not manually change the active pointer.

If Terraform apply partially succeeds and normal teardown cannot refresh state, use an
incident-specific rescue authorization. The rescue path may only initialize the exact backend,
create and validate a saved destroy-only plan, apply that plan, and independently verify absence.

## Teardown verification

The independent teardown job retrieves the authority recorded before apply, captures live outputs,
creates and validates a saved destroy-only plan, and applies only that plan. It then checks every
named service resource, recursively confirms that Terraform state is empty, and inventories
resources carrying the run ID.

Only explicit service-specific not-found responses prove deletion. Authorization errors, API
errors, and unreadable state fail closed. A KMS key in AWS-mandated `PendingDeletion` is accepted
only when its alias is absent and the deletion date is recorded. A successful data path with failed
cleanup is a failed validation run.
