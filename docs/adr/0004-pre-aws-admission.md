# ADR 0004: Admit exact source bytes before AWS credential issuance

## Status

Accepted for AtlasRetail Part 4 Stage 3.

## Context

The frozen Part 4 contract requires separate execution and teardown confirmations, exact workload
and cost bounds, source provenance, an admission evidence domain, and clean teardown before lease
release. The earlier bounded workflow configured AWS credentials before validating its inputs,
generated source bytes only after infrastructure apply, did not bind a workflow rerun attempt, and
released the account lease regardless of teardown verification. Each gap could make the eventual
managed evidence ambiguous even when the data path itself behaved correctly.

## Decision

AtlasRetail uses a repository-only `admission` job before either AWS-capable job. It has
`contents: read` permission and cannot request an OIDC token. It validates the frozen contract and
target, requires the repository owner to dispatch exact `main`, requires distinct
`EXECUTE_ATLASRETAIL_PART4` and `DESTROY` confirmations, enforces canonical 100--2,000 order and
USD 1--5 bounds, and materializes the complete deterministic source tree.

The admission receipt separately records the provenance summary's semantic digest, the physical
summary-file digest, and a canonical digest over every relative source path, size, and file SHA-256.
It also binds the GitHub run ID and run attempt. The immutable artifact name includes both values.
The execute and teardown jobs independently rebuild the receipt from the downloaded bytes before
they can request AWS credentials. Derived managed manifests are written outside the admitted source
tree.

Rejected admission cannot reach AWS. An admitted execution failure still reaches teardown. A
persisted teardown authority permits the validated destroy path; an earlier lease-only failure must
instead prove empty Terraform state and clean AWS inventory. The account lease is released only
after one of those clean proofs succeeds.

## Consequences

- Input, operator, source, contract, target, run, and attempt identity are one fail-closed boundary.
- GitHub artifact transport is never treated as content verification.
- A rerun can reuse the same deterministic business source while producing a distinct admission
  receipt for its new attempt.
- Invalid dispatches consume no AWS credentials and require no teardown.
- Missing cleanup evidence retains the lease for explicit recovery rather than hiding residue.
- The admission-control result is `LOCAL_VERIFIED`; it is not an AWS execution, cost, runtime, or
  teardown claim.
