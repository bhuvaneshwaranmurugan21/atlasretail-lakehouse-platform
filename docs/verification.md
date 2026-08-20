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
| Local generation publication model | `LOCAL_VERIFIED` | Replay, rollback, backfill isolation, and stale-writer tests |
| GitHub OIDC identity | `AWS_VERIFIED` | Short-lived credentials issued to the repository's `main` branch |
| Terraform safety and teardown | `AWS_VERIFIED` | Saved plans, explicit resource checks, empty state, and recorded rescue runs |
| Glue, Iceberg, Step Functions data path | `DESIGNED` | Infrastructure reached Glue creation, but the managed workload did not execute |
| Runtime, throughput, Athena scan, and workload cost | `DESIGNED` | Collection code exists; no successful managed measurement exists |
| Sustained production operation | Not established | No continuous workload or operational-history evidence |

## Evidence requirements

Managed evidence must include the source commit, repository run identifier, AWS account and region,
input identity, execution status, result validation, and teardown status. Estimates and local
simulations are not promoted to managed measurements. A successful data path with failed cleanup
is a failed validation run.

Sanitized summaries may be committed under `evidence/`. Detailed logs remain attached to their
GitHub Actions runs and must not contain credentials or customer data.
