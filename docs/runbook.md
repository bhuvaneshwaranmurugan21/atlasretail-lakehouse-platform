# AWS validation runbook

## Current stop condition

Part 1 rebinds executable repository configuration to the target in
`.github/atlas-target.json`. Part 2 must proceed in order: merge the repository hardening, update
the live inline policy, pass the independent IAM baseline, deploy and verify the persistent
foundation, and commit its sanitized evidence. Do not dispatch plan, probe, controlled deployment,
or data-processing workflows before those gates pass.

Before a later bounded execution, do not dispatch the data-processing workflow unless the
read-only preflight records `PAID` and `ACTIVE` when AWS exposes an account-plan record, or records
the exact AWS missing-data response for this member account with current organization-shared
credit at or above the bounded run's cost ceiling. The definition-only Glue capability probe must
also create and delete its temporary job successfully.
The probe must report zero Glue job runs and independently verify cleanup. A visible Glue console
or available CloudShell session is not evidence of `glue:CreateJob` authorization. The previous
denial stopped during Terraform apply; no Glue, Step Functions, or Athena workload executed.
The probe and its always-running cleanup job use separate 900-second OIDC sessions intersected
with run-scoped policies for only the exact temporary role and Glue job. Both policies explicitly
deny Glue, Step Functions, Lambda, and Athena workload starts. The temporary Glue execution role
must have Glue-only trust, exact run ownership tags, and no inline or attached permissions.

## Preconditions

1. Load account `857229544428`, region `ap-southeast-2`, role, backend, repository, and branch from
   `.github/atlas-target.json`; fail if GitHub variables differ.
2. Keep the GitHub OIDC trust restricted to this repository's `main` branch.
   `infra/iam/atlasretail-github-role-trust-policy.json` is the canonical allowed-subject contract.
3. Confirm that the deployed inline policy matches
   `infra/iam/atlasretail-github-role-policy.json`.
4. Require a successful identity-only workflow and read-only environment preflight.
5. Require `freetier:GetAccountPlanState` to return `PAID` and `ACTIVE` when a plan record exists.
   If AWS returns the exact `ResourceNotFoundException` missing-data response for this member
   account, accept only while `evidence/aws/organization-shared-credit-baseline.json` is current,
   targets this account, attests active unrestricted sharing, and covers the run ceiling.
6. Run the definition-only Glue service probe and require exact source identity, an inert temporary
   role, exact job configuration, zero job runs, self-cleanup, independently verified cleanup with
   a fresh restricted session, and a digest-bound final evidence manifest.
7. Confirm that `atlasretail/main.tfstate` is readable and empty.
8. Confirm that the shared budget and account lease exist.
9. Use a unique run ID and begin with 500 synthetic orders.
10. Review the open correctness boundaries in `docs/correctness.md` before authorizing execution.

## Part 2 foundation gate

1. Merge the repository-only hardening before changing AWS.
2. Replace the live `AtlasRetailBoundedLabPolicy` with the exact checked-in JSON; the OIDC role
   cannot update its own permissions.
3. Dispatch `AWS IAM baseline verification` with `VERIFY_ATLASRETAIL_IAM` and require `PASS`.
4. Store the alert recipient as the GitHub Actions secret `AWS_BUDGET_ALERT_EMAIL`.
5. Dispatch `Shared AWS foundation` with `DEPLOY_ATLASRETAIL_FOUNDATION` and budget `20`.
6. Require exact stack outputs, encrypted and versioned TLS-only state storage, encrypted
   on-demand PITR tables, lease TTL, three budget alerts, contention/release evidence, an empty
   Terraform backend, and zero AtlasRetail workload resources.
7. Commit only sanitized verification summaries. Raw subscriber addresses and live IAM documents
   remain ephemeral workflow control files.

## Plan-only approval gate

The `AWS plan-only proof` workflow runs before any deployment authorization. It:

1. Obtains short-lived credentials through the repository-and-branch-bound OIDC role.
2. Verifies the paid account state when AWS exposes a plan record. For an organization member
   account with no plan record, it accepts only the exact AWS missing-data response plus current,
   account-bound organization-shared credit. It also verifies the monthly budget, current spend,
   and a five-dollar gross run ceiling.
3. Compares the live inline role policy with the checked-in policy and rejects managed-policy
   attachments or broader OIDC trust.
4. Reads the locked remote backend and proves that state and tagged inventory are clean.
5. Generates a fresh plan for the exact `main` commit and rejects updates, replacements, deletions,
   address substitutions, or any deviation from the exact 40 managed addresses and six read-only
   data-source addresses in the checked-in envelope.
6. Validates the planned managed lifecycle definition with the Step Functions API.
7. Repeats the state and inventory checks and proves that the planning operation created no
   persistent AtlasRetail infrastructure.
8. Publishes only sanitized inventory, validation results, source identity, and content hashes;
   the binary plan is never published or reused for deployment.

A later deployment must regenerate its own saved plan and compare it with the approved resource
envelope. A plan-only artifact is evidence for review, not deployment authority.

## Part 3 zero-workload controlled deployment

Part 3 proves that the current `main` commit can deploy and remove the 40-resource AtlasRetail
control plane without executing a data workload. Dispatch `AWS controlled deployment canary` only
after a current-source read-only preflight, definition-only Glue probe, and plan-only proof pass.
Provide the three exact prerequisite run IDs with `DEPLOY_ATLASRETAIL_CANARY`,
`DESTROY_AFTER_VERIFICATION`, and a budget ceiling from one to five dollars. The admission job
downloads those exact artifacts and fails unless all three bind to the deployment commit, account,
region, repository, branch, and run IDs; it also requires independent Glue-probe cleanup, zero
workload starts, an exact plan envelope, and zero persistent plan change. The workflow regenerates
and validates its own saved create-only plan; the earlier plan binary is never published or used as
deployment authority.

The canary must report an active control plane, exactly 40 Terraform-managed resources, six
read-only IAM policy-document data sources, and `PASS` for every readiness check. It must also
prove an empty DynamoDB table and Glue catalog, exact S3 object-version inventories, zero Glue job
runs, zero Step Functions executions, no events in any of the three workload log groups, and zero
Athena query executions. Deployment and teardown credentials are separate one-hour OIDC sessions
intersected with policies that explicitly deny all Glue, Step Functions, Lambda, and Athena
workload-start APIs. Input generation, immutable batch upload,
`start-job-run`, `start-execution`, Lambda invocation, and Athena query execution are forbidden in
this workflow. Any workload activity invalidates the Part 3 claim.

The independent teardown job runs after every admitted deployment attempt. It recomputes and
matches the immutable infrastructure digest before accepting teardown authority, creates and
validates a saved exact 40-address destroy-only plan after a successful deployment, applies only
that plan, and proves empty Terraform
state and zero unexpected tagged resources, and releases the lease only after cleanup passes. A KMS
key is accepted only in AWS-mandated `PendingDeletion` with its alias absent and deletion date
recorded. A successful deployment with failed or skipped teardown is a failed Part 3 run. Ephemeral
Terraform outputs remain only in the one-day teardown-recovery artifact and are removed before the
final 30-day evidence artifact is summarized. If deployment fails after a partial apply, teardown
may delete a strict subset of the same 40 known addresses so cleanup is not stranded; that recovery
path can never earn the Phase 5 deployment claim.

The final sanitized summary is `part-3-summary.json`. It may claim `AWS_DEPLOYMENT_VERIFIED` only
when prerequisite admission, deployment, zero-workload, exact apply and destroy envelopes, both
session boundaries, source identity, budget checks, a monotonic runtime timeline, and teardown all
pass. Immediate budget verification is not a settled-invoice claim; actual billed cost remains
`UNCLAIMED`. Until attributable AWS evidence satisfies the complete contract, the deployment claim
remains `UNCLAIMED`.

## Part 4 frozen execution contract

Part 4 is governed by `contracts/part4/run-contract.json`. Validate it with
`python scripts/validate_part4_contract.py` before changing any Part 4 implementation. The
validator binds the contract to the exact checked-in `.github/atlas-target.json`, requires a
manually dispatched `main`-branch source, freezes 100/500/2,000-order bounds and a five-dollar
maximum run ceiling, and requires distinct `EXECUTE_ATLASRETAIL_PART4` and `DESTROY`
confirmations. The emitted canonical SHA-256 identifies the contract independently of JSON
formatting.

The contract requires ten proofs: eight Step Functions executions, six Glue job runs, direct stale
publisher rejection, and bounded Athena verification. Expected failures must carry their exact
semantic signal; a generic `FAILED` status is insufficient. Evidence collection, artifact upload,
saved-plan teardown, empty Terraform state, clean AWS inventory, and safe lease release are part of
the result. A successful workload with missing evidence or failed cleanup is a failed Part 4 run.

Stage 1 freezes and locally validates this contract; it performs no AWS operation and creates no
new `AWS_VERIFIED` claim. Existing managed evidence remains attributed to its original source.
Production readiness, sustained scale, SLA behaviour, and settled billing remain `UNCLAIMED`.

Stage 3 closes the previously recorded dispatch gaps: the manual input now advertises the exact
one-to-five-dollar range and exposes the distinct Part 4 execution confirmation. This does not by
itself authorize a managed run. Do not dispatch Part 4 until the later execution and evidence
stages are complete.

### Stage 2 deterministic source provenance

Stage 2 binds every physical input family to `contracts/part4/scenario-sources.json`. Validate the
catalogue and its contract and target digests with `python scripts/validate_part4_sources.py`.
Materialize the five bounded source families with `atlasretail generate-sources`; this produces a
strict provenance receipt for each source and a separate mutation receipt for the tamper proof.

The receipts deliberately distinguish three identities: canonical business-record digests,
compressed object-byte digests, and the execution provenance that names the source commit,
contract, schemas, generator parameters, Python runtime, and zlib runtime. Gzip members use a
fixed level-nine header with `mtime=0`, no filename, and OS byte 255, so wall-clock time, output
directory, timezone, locale, and hash seed cannot change their bytes. Failure and recovery bind to
one physical source; replay reuses the exact success registration. Substitute recovery sources,
undeclared scenarios, changed schemas, symlinks, missing fields, and modified bytes fail closed.
The identity separation and the pre-upload-to-managed boundary are recorded in
`docs/adr/0003-source-provenance.md`.

Stage 2 performs no AWS operation and adds no `AWS_VERIFIED` claim. CI regenerates the complete
100-order source set twice, validates each set independently, compares every byte, and retains only
compact receipts as the `part4-stage2-source-provenance` artifact. The current Part 4 dispatch
remains prohibited at the Stage 2 boundary because source provenance alone is not run admission.

### Stage 3 pre-AWS admission and immutable source handoff

Stage 3 adds a dedicated admission job with no OIDC permission and no AWS or Terraform command.
It requires the repository owner to dispatch the exact `main` source, binds the run ID and attempt,
enforces canonical 100--2,000 order and one-to-five-dollar inputs, and requires separate exact
`EXECUTE_ATLASRETAIL_PART4` and `DESTROY` confirmations. It materializes and independently
validates all five source families before any AWS credential can be requested.

`contracts/part4/admission-receipt.schema.json` defines the strict handoff. The receipt binds the
frozen contract, target, catalogue and schema digests; GitHub source and operator identity; the
semantic provenance-summary digest; the physical summary-file digest; and a canonical tree digest
over every relative path, size and source-file SHA-256. Artifact names include both run ID and run
attempt. Execute and teardown independently rebuild the complete receipt from downloaded bytes
before OIDC. Derived managed manifests are written outside the admitted tree.

Rejected admission cannot reach AWS. Admitted execution failure still reaches teardown. The lease
is released only after either full teardown verification or a lease-only failure path proves empty
Terraform state and clean AWS inventory. Validate the repository control structure with
`python scripts/validate_part4_admission_controls.py`.

Stage 3 performs no AWS operation and adds no `AWS_VERIFIED` claim. CI retains a compact
`part4-stage3-admission-controls` artifact with `LOCAL_VERIFIED` scope. The identity and cleanup
design is recorded in `docs/adr/0004-pre-aws-admission.md`. Part 4 dispatch remains prohibited
until its later managed-execution stages are complete.

Because admission artifacts bind `github.run_attempt`, do not use **Re-run failed jobs** for a
future Part 4 run. Re-run all jobs or create a fresh dispatch so the admission job produces the
artifact for the new attempt. A downstream job cannot consume an earlier attempt's artifact.

### Stage 4 contract-complete evidence readiness

Stage 4 replaces the permissive pre-teardown summary boundary with two semantic authorities.
`scripts/validate_part4_execution_evidence.py` validates the run-bound execution evidence, records
`AWS_EXECUTION_VALIDATED_PENDING_TEARDOWN`, and keeps the contract claim level `UNCLAIMED`.
`scripts/finalize_part4_evidence.py` is the sole code
path allowed to emit `AWS_VERIFIED`, and only after the saved destroy plan, clean AWS and Terraform
inventories, target-bound teardown session, post-teardown budget, exact-owner lease deletion, and
consistent-read lease absence all pass.

The validators require the contract's exact eight Step Functions executions and six Glue runs,
semantic failure signals, replay without a second Glue run, failure/recovery identity continuity,
pointer invariants, stale-publisher winner stability, two generation-pinned Athena queries,
non-empty run-bound Glue/States/Lambda log exports, runtime/metered usage, and complete provenance.
Validate repository readiness with `python scripts/validate_part4_stage4_controls.py`. CI runs the
validator twice, diffs its deterministic receipts, and retains
`part4-stage4-evidence-readiness-<run-id>`.

Stage 4 performs no AWS operation. Its maximum claim is `LOCAL_VERIFIED` with
`aws_execution: false`. Do not dispatch the Part 4 bounded workflow solely on Stage 4 readiness;
the later managed-execution authorization stages must still be completed.

## Deploy and execute

When the later Part 4 stages authorize execution, run `AWS bounded lab` manually with
`order_count=500`, `budget_ceiling_usd=5`,
`confirm_execute=EXECUTE_ATLASRETAIL_PART4`, and `confirm_destroy=DESTROY`. The workflow:

1. Admits the exact operator, source, attempt, bounds, confirmations and deterministic source bytes
   without AWS credentials.
2. Revalidates the immutable admission artifact before requesting OIDC credentials.
3. Validates the account and region, then acquires the account-wide DynamoDB lease.
4. Initializes the locked remote Terraform state.
5. Proves that state and tagged inventory are clean.
6. Persists teardown authority before infrastructure creation.
7. Creates and machine-validates a saved create-only plan and validates the planned ASL definition
   through the Step Functions API.
8. Applies only that saved plan.
9. Verifies the exact deployed control plane before uploading or executing any workload.
10. Uploads only the admitted inputs with exact S3 version and checksum evidence.
11. Runs success, replay, batch-conflict, object-tamper, injected-failure, recovery, temporal-overlap,
   financial-mismatch, and stale-publisher scenarios.
12. Resolves one published generation and executes bounded Athena validation across all six tables.
13. Builds a non-final execution checkpoint from histories, logs, results, runtime, and budget.
14. Invokes independent teardown for every admitted execution outcome, verifies clean inventories,
    and releases the exact lease only after a consistent-read absence proof.
15. Finalizes the evidence only after all 20 contract domains pass.

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
The previous environment's rescue workflow and authorizations are a non-executable forensic archive
under `docs/incidents/legacy/`; they must never be dispatched against the current target.

## Teardown verification

The independent teardown job retrieves the authority recorded before apply, captures live outputs,
creates and validates a saved destroy-only plan, and applies only that plan. It then checks every
named service resource, recursively confirms that Terraform state is empty, and inventories
resources carrying the run ID.

Only explicit service-specific not-found responses prove deletion. Authorization errors, API
errors, and unreadable state fail closed. A KMS key in AWS-mandated `PendingDeletion` is accepted
only when its alias is absent and the deletion date is recorded. A successful data path with failed
cleanup is a failed validation run.
