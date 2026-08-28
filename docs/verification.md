# Verification policy

AtlasRetail separates design, deterministic local validation, managed-environment evidence, and
sustained operational measurement. A result is attributed to the exact source commit and
environment that produced it.

| Level | Meaning |
|---|---|
| `DESIGNED` | Architecture or implementation exists but has not executed in the stated environment |
| `LOCAL_VERIFIED` | Deterministic implementation passed locally and in CI |
| `AWS_VERIFIED` | A bounded AWS operation produced attributable run evidence |
| `PRODUCTION_MEASURED` | Behaviour was measured under a sustained production workload |

## Current evidence boundary

| Area | Level | Basis |
|---|---|---|
| Domain and retail invariants | `LOCAL_VERIFIED` | Unit, behavioural, and deterministic failure-scenario tests |
| Immutable object manifest | `LOCAL_VERIFIED` | Canonical digest and exact S3 identity contract tests |
| Glue 5 Spark and Iceberg runtime compatibility | `LOCAL_VERIFIED` | Pinned Glue 5-compatible runtime executes Spark validation, real local Iceberg snapshots, replay, and failure recovery |
| Managed lifecycle and serving resolver | `LOCAL_VERIFIED` | Conditional-transition, publication, recovery, and query-boundary tests |
| GitHub OIDC identity | `AWS_VERIFIED` | Current-target short-lived credentials issued to the repository's `main` branch |
| Organization-shared credit safety | `OWNER_ATTESTED` | Management-account credit balance and unrestricted organization sharing were reviewed; the attestation expires quickly and must be refreshed |
| IAM and persistent foundation | `AWS_VERIFIED` | [Run 32926893305](https://github.com/bhuvaneshwaranmurugan21/atlasretail-lakehouse-platform/actions/runs/32926893305) verified exact live IAM parity, hardened persistent resources, budget alerts, lease contention and release, an empty backend, and zero AtlasRetail workload resources |
| Current-target plan-only environment proof | `AWS_VERIFIED` | [Run 33060606145](https://github.com/bhuvaneshwaranmurugan21/atlasretail-lakehouse-platform/actions/runs/33060606145) verified the merged bounded Lambda registration reconciliation, post-fix empty state, three permitted KMS keys pending deletion, organization-shared credit, budget headroom, a bounded create-only plan, the managed definition, and zero persistent change |
| Current-target Glue definition capability | `AWS_VERIFIED` | [Run 32930567869](https://github.com/bhuvaneshwaranmurugan21/atlasretail-lakehouse-platform/actions/runs/32930567869) verified bounded `glue:CreateJob` access without starting a workload, then independently verified deletion of the probe job and temporary IAM role |
| Current-target partial-apply recovery and teardown | `AWS_VERIFIED` | [Run 32952618876](https://github.com/bhuvaneshwaranmurugan21/atlasretail-lakehouse-platform/actions/runs/32952618876) validated a 39-resource destroy-only plan, applied that saved plan, proved empty Terraform state and zero unexpected tagged resources, and verified the remaining KMS key was scheduled for deletion |
| Current-target successful saved-plan deployment and teardown | `AWS_VERIFIED` | [Run 33167646509](https://github.com/bhuvaneshwaranmurugan21/atlasretail-lakehouse-platform/actions/runs/33167646509) applied the validated 40-resource saved plan, completed the bounded workload, destroyed the same 40 resources, proved empty Terraform state and zero unexpected tagged resources, and verified KMS pending deletion |
| Glue, Iceberg, Step Functions data path | `AWS_VERIFIED` | Run 33167646509 proved success, replay, conflict rejection, failure isolation, deterministic recovery, temporal and financial gates, S3 object-identity rejection, stale-publisher rejection, one six-table serving resolution, and matching Athena results |
| CloudWatch execution evidence | `AWS_VERIFIED` | Run 33167646509 exported 28,921 Glue events, 187 Step Functions events, and 84 Lambda events; the evidence gate requires each export to be non-empty |
| Bounded runtime, Athena scan, and workload cost estimate | `AWS_VERIFIED` | Run 33167646509 measured 1,325 seconds to evidence, 1,562 Glue DPU-seconds, two Athena queries scanning 2,192 bytes, and a $0.191016 Glue-plus-Athena estimate; minor charges and settled billing remain outside the claim |
| Sustained production operation | Not established | No continuous workload or operational-history evidence |

The runtime-integration job pins the AWS Glue 5 runtime versions: Python 3.11, Spark 3.5.4, and
the SHA-512-verified Iceberg 1.7.1 runtime. It remains the deterministic local compatibility gate.
Run 33167646509 separately establishes the bounded managed behaviour of Glue, S3, Glue Data
Catalog, Step Functions, Lambda, DynamoDB, CloudWatch Logs, and Athena for its attributed source
commit and inputs; it does not establish production scale or sustained operation.

Earlier plan, partial-deployment, and rescue runs remain attributable historical evidence for their
original environment. They establish incident handling and control design, but they do not promote
the current target's IAM, infrastructure, or managed workloads to `AWS_VERIFIED`.

## Evidence requirements

Managed evidence must include the source commit, repository run identifier, AWS account and region,
input identity, execution status, result validation, and teardown status. Estimates and local
simulations are not promoted to managed measurements. A successful data path with failed cleanup
is a failed validation run.

Sanitized summaries may be committed under `evidence/`. Detailed logs remain attached to their
GitHub Actions runs and must not contain credentials or customer data.

The plan-only artifact excludes the binary saved plan and raw expanded resource values. It retains
the source commit, run identifier, resource address/type/action inventory, validation results,
budget envelope, before/after baseline proof, and SHA-256 digests of the unabridged ephemeral plan.

The Glue capability artifact proves only definition-plane access and cleanup. It records zero job
runs and no workload execution, so it does not promote the managed transformation or data path.

The recovery artifact separates the failed execution from its successful teardown retry. It proves
the current target can recover exact Terraform state and independently verify cleanup, but it does
not promote the deployment, managed transformation, replay, failure, recovery, or Athena data-path
claims.

The bounded-run artifact for 33167646509 promotes those managed data-path claims for its exact
500-order workload. The committed snapshot retains digests and sanitized summaries; raw execution
histories, CloudWatch events, caller identity, and live resource identifiers remain only in the
expiring workflow artifact.
