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
| Part 4 deterministic source provenance | `LOCAL_VERIFIED` | Five contract-bound source families, deterministic compressed bytes, separate semantic/file identities, strict receipts, and independent CI reproduction |
| Part 4 pre-AWS admission controls | `LOCAL_VERIFIED` | Exact operator, `main` source, run attempt, distinct confirmations, cost/workload bounds and source tree are revalidated before OIDC; lease release requires verified clean state |
| Part 4 contract-complete evidence readiness | `LOCAL_VERIFIED` | Execution checkpoint cannot claim final verification; the sole finalizer requires all 20 domains, 18 provenance fields, clean teardown, post-teardown budget proof, and consistent-read lease absence |
| Part 4 immutable teardown authority and deterministic recovery | `LOCAL_VERIFIED` | Exact run/attempt/source/plan authority, immutable artifact and lease binding, cleanup-only recovery, saved destroy-plan integrity, inventory proof and adversarial CI validation; Stage 5 performs no AWS operation |
| Part 4 Stage 6 managed execution and finality | `AWS_VERIFIED` | [Run 33329861907](https://github.com/bhuvaneshwaranmurugan21/atlasretail-lakehouse-platform/actions/runs/33329861907) admitted the exact current-source prerequisite chain, passed all 20 contract domains, finalized after exact teardown and lease release, and was independently followed by clean-inventory run 33331233341 |
| GitHub OIDC identity | `AWS_VERIFIED` | Current-target short-lived credentials issued to the repository's `main` branch |
| Organization-shared credit safety | `OWNER_ATTESTED` | Management-account credit balance and unrestricted organization sharing were reviewed; the attestation expires quickly and must be refreshed |
| IAM and persistent foundation | `AWS_VERIFIED` | [Run 32926893305](https://github.com/bhuvaneshwaranmurugan21/atlasretail-lakehouse-platform/actions/runs/32926893305) verified exact live IAM parity, hardened persistent resources, budget alerts, lease contention and release, an empty backend, and zero AtlasRetail workload resources |
| Current-source plan-only environment proof | `AWS_VERIFIED` | [Run 33329689861](https://github.com/bhuvaneshwaranmurugan21/atlasretail-lakehouse-platform/actions/runs/33329689861) verified source `08559b0`, an absent account lease, empty Terraform state, no unexpected active resources, organization-shared credit, budget headroom, exact live IAM parity, a bounded 40-resource create-only plan, the managed definition, and zero persistent change |
| Current-source Glue definition capability | `AWS_VERIFIED` | [Run 33329607444](https://github.com/bhuvaneshwaranmurugan21/atlasretail-lakehouse-platform/actions/runs/33329607444) verified exact `glue:CreateJob` definition-plane access under a run-scoped session, an inert no-policy Glue role, exact configuration and ownership, zero job runs, self-cleanup, and absence under an independent cleanup-only OIDC session |
| Current-target partial-apply recovery and teardown | `AWS_VERIFIED` | [Run 32952618876](https://github.com/bhuvaneshwaranmurugan21/atlasretail-lakehouse-platform/actions/runs/32952618876) validated a 39-resource destroy-only plan, applied that saved plan, proved empty Terraform state and zero unexpected tagged resources, and verified the remaining KMS key was scheduled for deletion |
| Current-source zero-workload controlled deployment and exact-state teardown | `AWS_VERIFIED` | [Run 33255708391](https://github.com/bhuvaneshwaranmurugan21/atlasretail-lakehouse-platform/actions/runs/33255708391) admitted the exact current-source prerequisite chain, applied only the validated 40-resource saved plan, verified the control plane with zero workload, applied only the validated 40-resource destroy plan, and proved zero active residue |
| Stage 6 deterministic recovery | `AWS_VERIFIED` | [Run 33328391707](https://github.com/bhuvaneshwaranmurugan21/atlasretail-lakehouse-platform/actions/runs/33328391707) validated the exact failed-run authority, applied a 40-resource cleanup-only destroy plan, passed all 20 cleanup checks, and released the recovery-bound lease; it makes no workload claim |
| Independent post-teardown clean inventory | `AWS_VERIFIED` | [Run 33331233341](https://github.com/bhuvaneshwaranmurugan21/atlasretail-lakehouse-platform/actions/runs/33331233341) independently proved the account lease absent, Terraform state empty, no unexpected active AtlasRetail resources, and 13 historical KMS keys pending deletion with no aliases |
| Current-source managed workload and teardown | `AWS_VERIFIED` | [Run 33329861907](https://github.com/bhuvaneshwaranmurugan21/atlasretail-lakehouse-platform/actions/runs/33329861907) applied the validated 40-resource saved plan, completed its bounded workload, destroyed the same 40 resources, proved empty Terraform state and zero unexpected tagged resources, released the lease, and emitted the final claim |
| Glue, Iceberg, Step Functions data path | `AWS_VERIFIED` | Run 33329861907 proved success, replay, conflict rejection, failure isolation, deterministic recovery, temporal and financial gates, S3 object-identity rejection, stale-publisher rejection, one six-table serving resolution, and matching Athena results |
| CloudWatch execution evidence | `AWS_VERIFIED` | Run 33329861907 exported 29,538 Glue events, 184 Step Functions events, and 90 Lambda events with complete pagination and non-empty source gates |
| Controlled-deployment runtime and budget envelope | `AWS_VERIFIED` | Run 33255708391 measured 351 seconds from apply start to evidence collection and verified a $5 gross-cost ceiling against $19.551 budget headroom before deployment, after deployment, and after teardown; actual billed cost is `UNCLAIMED` |
| Bounded workload runtime, Athena scan, and workload cost estimate | `AWS_VERIFIED` | Run 33329861907 measured 1,646.816 seconds from execution start to finality, 1,323 Glue DPU-seconds, two Athena queries scanning 2,192 bytes, and a $0.161805 Glue-plus-Athena estimate; minor charges and settled billing remain outside the claim |
| Sustained production operation | Not established | No continuous workload or operational-history evidence |

The runtime-integration job pins the AWS Glue 5 runtime versions: Python 3.11, Spark 3.5.4, and
the SHA-512-verified Iceberg 1.7.1 runtime. It remains the deterministic local compatibility gate.
Run 33329861907 establishes the bounded managed behaviour of Glue, S3, Glue Data
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

The Stage 3 admission-control artifact is repository-only evidence. It proves workflow permission
ordering, exact input bounds, attempt-bound immutable source handoff, independent receipt
revalidation, and clean-only lease-release routing. It contains `aws_execution: false` and cannot
promote any infrastructure, workload, runtime, cost, CloudWatch, Athena, or teardown claim to
`AWS_VERIFIED`.

The Stage 4 evidence-readiness artifact is also repository-only evidence. It proves the strict
schemas, workflow ordering, compact target-region session intersections, single final claim
authority, and positive/adversarial validation behavior. It contains `aws_execution: false` and
`claim_level: LOCAL_VERIFIED`. It does not prove that a Part 4 managed run occurred.

The Stage 5 teardown-authority artifact is repository-only evidence. It proves schema and workflow
ordering, exact attempt/source/plan bindings, conditional lease transitions, a cleanup-only manual
recovery route, saved destroy-plan integrity checks, and adversarial validator behavior. It contains
`aws_execution: false` and `claim_level: LOCAL_VERIFIED`. A later successful recovery artifact may
prove cleanup for its exact failed run, but it cannot promote workload, correctness, scale or cost
claims.

The Stage 6 managed-execution readiness artifact is repository-only evidence. It proves the exact
prerequisite admission chain, workflow and credential bounds, destroy-plan binary binding,
structured failure finalization, and lease-only recovery constraints. It contains
`aws_execution: false` and `claim_level: LOCAL_VERIFIED`; it does not claim the managed Stage 6 run
has occurred.

The completed Stage 6 evidence is separate from that readiness artifact. Run `33329861907` is the
current-source final managed proof: the sole finalizer emitted `AWS_VERIFIED` only after all 20
domains, the saved destroy plan, clean AWS and Terraform inventories, post-teardown budget proof,
and exact consistent-read lease release passed. Run `33331233341` then independently reread the
account and backend and found no active residue.

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

The bounded-run artifact for `33329861907` promotes those managed data-path and finality claims for
its exact 500-order workload. The committed snapshot retains digests and sanitized summaries; raw
execution histories, CloudWatch events, caller identity, live resource identifiers, and Terraform
plan payloads remain only in the expiring workflow artifact. Run `33167646509` remains valid
historical evidence for its attributed source.

The Phase 5 controlled-deployment evidence is intentionally a zero-workload infrastructure proof. It does not re-claim managed data processing, replay, failure isolation, Athena result correctness, production scale, or settled cost for source `c4f2a24`; those dimensions remain attributed to their explicitly listed evidence runs.
