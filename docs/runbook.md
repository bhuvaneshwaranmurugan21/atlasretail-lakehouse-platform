# AWS bounded-execution runbook

## Preconditions

1. CI and Terraform validation are green.
2. Account spend is below the portfolio stop threshold.
3. No other project holds the portfolio lab lease.
4. The workflow input includes a unique run ID and maximum runtime.

## Execute

1. Apply the tagged lab topology and capture Terraform outputs.
2. Generate deterministic order, return, inventory, and dimension inputs.
3. Upload immutable manifests to the run-scoped landing prefix.
4. Run the Glue Iceberg job and capture job-run and snapshot identifiers.
5. Execute reconciliation and cost-aware Athena queries.
6. Inject a corrupt contract and prove publication is blocked.
7. Inject a pre-commit failure, replay, and prove identical terminal state.
8. Execute an isolated late-arrival backfill and then publish through conditional pointer update.
9. Export metrics, selected logs, query statistics, and the evidence manifest.

## Teardown

Run Terraform destroy even after a failed experiment, list resources by `Project` and `RunId`,
verify that no billable compute remains, and record expected KMS keys pending deletion.

