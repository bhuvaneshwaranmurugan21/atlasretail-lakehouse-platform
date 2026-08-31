# ADR 0011: Establish evidence traceability before closing completion gaps

## Status

Accepted

## Context

Part 5 Stage 1 freezes seven original engineering objectives and twelve gates that must all be
satisfied before AtlasRetail can be called complete. A frozen list alone does not show which prior
authority supports each objective, which gates still need current validation, or exactly what
evidence is required to close an incomplete gate. Treating inherited evidence as a blanket pass
would permit claim inflation, while treating every historical proof as stale would discard valid
managed-workload, recovery, clean-inventory, and release authorities.

Stage 2 must not modify the frozen managed surface under `aws`, `contracts`, `infra`, `scripts`, or
`src`. It performs no AWS operation. It also cannot commit its final receipt in the same change as
the controls because that receipt must name the actual controls merge and its successful `main` CI
run.

## Decision

Part 5 Stage 2 defines a strict completion-gap schema, deterministic traceability builder,
fail-closed validator, adversarial tests, CI integration, and repository documentation under
`release/part5/stage2`. The model covers every Stage 1 objective and gate exactly once and accepts
only four statuses:

- `PRESERVED_PASS` — an immutable predecessor authority remains valid without a new claim;
- `CURRENT_PASS_RECHECK_REQUIRED` — current evidence is encouraging but must be rerun at the final
  completion candidate;
- `PARTIAL` — some authority exists, but the frozen gate is not fully satisfied; and
- `OPEN` — the required completion event has not occurred.

Every gate not marked `PRESERVED_PASS` has exactly one blocking gap with a stable identifier,
severity, and explicit closure evidence. Six predecessor gates remain preserved. Six gates remain
open, partial, or subject to a final recheck; none is promoted for convenience.

Publication is deliberately split:

1. Merge the Stage 2 controls only after complete CI passes. The accepted controls state is
   `TRACEABILITY_CONTROLS_READY`.
2. Require successful `main` CI for the exact controls merge.
3. Build `evidence/part5/stage2/completion-gap.json` from that merge commit and CI run ID.
4. Reconstruct and validate the receipt in an evidence-only pull request.
5. Accept the published state `GAP_BASELINE_RECORDED` only after that second change passes CI.

The final receipt binds the exact Stage 1 contract, Part 4 closure receipt, Part 4 release receipt,
schema digest, controls merge, and controls `main` CI run. Its self-digest prevents an altered
status, authority, gap, or claim from being accepted without detection.

## Claim boundary

Stage 2 is repository-only `LOCAL_VERIFIED` with `aws_execution: false`. It preserves prior
`AWS_VERIFIED` authorities without claiming a new managed execution. Project completion remains
false, Part 5 completion remains false, production remains unclaimed, sustained operation remains
unestablished, and actual billed cost remains `UNCLAIMED`.

## Failure behavior

Missing objective or gate coverage, an unsupported status, a removed or non-blocking gap, authority
digest drift, schema weakening, receipt digest mismatch, publication against a nonexistent or
pre-Stage-2 commit, missing successful `main` CI attribution, frozen-root drift, absent CI wiring,
documentation gaps, or professional naming violations fail closed. These failures must be fixed at
their source; a status may not be promoted and a gate may not be removed to obtain a passing result.
