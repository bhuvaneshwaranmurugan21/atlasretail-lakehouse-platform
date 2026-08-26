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
| Current-target plan-only environment proof | `AWS_VERIFIED` | [Run 32929299555](https://github.com/bhuvaneshwaranmurugan21/atlasretail-lakehouse-platform/actions/runs/32929299555) verified organization-shared credit, budget headroom, exact IAM parity, a bounded create-only plan, the managed definition, and zero persistent change |
| Current-target Terraform safety and teardown | `DESIGNED` | Locally tested controls; no current-target deployment or teardown evidence exists |
| Glue, Iceberg, Step Functions data path | `DESIGNED` | Hardened managed path exists, but the new workload has not executed |
| Runtime, throughput, Athena scan, and workload cost | `DESIGNED` | Collection code exists; no successful managed measurement exists |
| Sustained production operation | Not established | No continuous workload or operational-history evidence |

The runtime-integration job pins the AWS Glue 5 runtime versions: Python 3.11, Spark 3.5.4, and
the SHA-512-verified Iceberg 1.7.1 runtime. No AWS credentials are configured, and its Iceberg
catalog uses local filesystem storage. This establishes runtime and table-format compatibility,
not the behaviour of the managed Glue service, S3, Glue Data Catalog, or Athena. Those services
require attributable bounded AWS evidence before any claim is promoted to `AWS_VERIFIED`.

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
