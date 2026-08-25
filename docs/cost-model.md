# Cost model

The ephemeral AWS environment is intended for short, attributable validation runs rather than
continuous operation. Exact workload cost remains unmeasured because the managed data path has not
completed.

| Driver | Bound | Control |
|---|---:|---|
| Glue | Success, injected failure, recovery, and invalid-data gates | G.1X, two workers, per-run timeout |
| Step Functions | Bounded transitions per named scenario | Standard workflow and execution timeout |
| S3 | Synthetic input and compact Iceberg output | Lifecycle expiry and teardown |
| DynamoDB | Small on-demand control and lease tables | On-demand capacity and teardown |
| Athena | Exact validation queries only | Workgroup byte cutoff |
| CloudWatch | Short-lived execution logs | Seven-day retention and teardown |
| KMS | One temporary data key | Alias deletion and scheduled key deletion |
| Persistent foundation | Small versioned S3 state plus two empty on-demand DynamoDB tables with PITR | Exact named resources and a $20 gross-cost budget with 50%, 80%, and 100% alerts |

## Measurement model

The workflow records elapsed seconds, Glue DPU-seconds, Athena bytes scanned, and the created
resource inventory. It calculates an immediate estimate from declared reference rates. That value
is useful during teardown but is not a settled bill.

Settled cost must be recorded later from AWS billing data and attributed by run identifier and
source commit. Regional pricing, requests, storage, logging, orchestration, taxes, and services not
included by the immediate calculator can create a difference.

AWS Budgets provide delayed alerts rather than an instantaneous spending cutoff. The saved-plan
resource ceiling, workload limit, execution timeout, account lease, and independent teardown are
the primary runtime controls.

The target member account can show zero locally owned credits while eligible organization credits
remain available through consolidated billing. A short-lived checked-in attestation records that
manual management-account verification; it is not a real-time balance API and automatically
becomes unusable after its `valid_until` timestamp.
