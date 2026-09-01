# ADR 0012: Verify operational handoff through deterministic rehearsal

## Status

Accepted

## Context

Part 5 Stage 2 records `P5-GAP-003` as a blocking, partially satisfied operational-handoff gap.
Part 4 preserves a bounded operation run, cleanup-only recovery, final clean inventory, release
integrity, incident history, and a detailed runbook. Those authorities describe the system, but
they do not yet prove that operation, recovery, and escalation decisions can be reproduced as one
complete handoff. Treating documentation presence as verified handoff would leave ambiguous
recovery selection and automatic-retry risk unresolved.

Stage 3 must not modify the frozen surface under `aws`, `contracts`, `infra`, `scripts`, or `src`.
It must also avoid a new AWS operation because the required evidence is a repository-only
rehearsal, not another managed workload or incident drill.

## Decision

Stage 3 defines four deterministic scenarios under `release/part5/stage3`: normal operation,
authority-bound recovery, lease-only recovery, and stop-and-escalate. Each scenario binds exact
workflow or incident authorities, an expected decision, required evidence, and prohibited
actions. The validator requires one operation path, two mutually exclusive recovery paths, and one
escalation path.

The authority-bound path accepts only the failed run, attempt, source, immutable teardown
authority, destroy-only plan, clean inventory, and lease release. The lease-only path is permitted
only for an exact `ACQUIRED` lease with no teardown authority and empty Terraform and AWS
inventories. Any state, resource, evidence, authorization, invariant, or teardown ambiguity must
stop and escalate; automatic retry is prohibited.

Publication is split. The controls change reaches `HANDOFF_CONTROLS_READY` after complete CI. A
separate receipt is then built from the controls merge and its successful `main` CI run, verified
in an evidence-only change, and accepted as `OPERATIONAL_HANDOFF_VERIFIED` only after that change
passes CI.

Stage 3 closes only `P5-GAP-003`. Gaps `P5-GAP-001`, `P5-GAP-002`, `P5-GAP-004`, `P5-GAP-005`, and
`P5-GAP-006` remain blocking.

## Claim boundary

Stage 3 is repository-only `LOCAL_VERIFIED` with `aws_execution: false`. It does not claim a live
incident drill, production readiness, sustained operation, a new managed workload, or settled
billing. Project completion remains false and actual billed cost remains `UNCLAIMED`.

## Failure behavior

Missing scenario coverage, ambiguous recovery selection, automatic retry, manual deletion,
authority drift, claim inflation, additional gap closure, frozen-root drift, schema weakening,
receipt mutation, or publication without successful `main` CI fails closed. Correct the source of
the disagreement; do not remove a scenario or prohibited action to obtain a pass.
