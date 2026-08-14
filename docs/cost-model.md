# Cost model

The lab is designed to remain a small, measurable experiment rather than a permanently running
platform. Exact cost must come from the AWS evidence run; the figures below are pre-run estimates,
not measured claims.

| Driver | Bound | Cost control |
|---|---:|---|
| Glue | Success, injected failure, and deterministic recovery | G.1X, two workers, 12-minute per-run timeout |
| Step Functions | Fewer than 50 transitions per scenario | Standard workflow, two scenarios |
| S3 | Synthetic input and compact Iceberg output | Lifecycle expiry and destroy |
| DynamoDB | Tiny on-demand control tables | On-demand billing and destroy |
| Athena | Only bounded verification queries | Workgroup byte cutoff |
| CloudWatch | Short-lived logs | Seven-day retention and destroy |
| KMS | One temporary key | Scheduled deletion on destroy |

The workflow records elapsed seconds, Glue DPU-seconds, Athena bytes scanned, resource inventory,
and an immediate metered estimate. Saved-plan resource ceilings and the independent teardown job
bound the infrastructure lifecycle. The calculator uses AWS's public reference rates of $0.44 per
Glue DPU-hour and $5 per Athena TB scanned, with the documented 10 MB Athena minimum. Regional
pricing can vary, and the estimate excludes small request/storage/orchestration charges. Cost
Explorer is useful only after billing data settles; it is not substituted for immediate metering.
