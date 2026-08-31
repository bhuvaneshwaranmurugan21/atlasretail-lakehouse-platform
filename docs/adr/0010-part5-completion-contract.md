# ADR 0010: Freeze the final project-completion contract

## Status

Accepted

## Context

Part 4 ended with an immutable `v0.1.0` release. That release preserves a bounded managed workload,
deterministic cleanup-only recovery, final read-only clean inventory, a runtime-equivalent 107-file
managed surface, and checksum-bound release evidence. Part 5 is the final project part, so an
informal or moving completion definition would permit later work to omit an original objective,
inflate an evidence claim, or declare completion while a required validation remains incomplete.

Adding Part 5 controls under `aws`, `contracts`, `infra`, `scripts`, or `src` would alter the frozen
runtime inventory. Stage 1 must also remain repository-only and cannot refresh, replace, or inherit
the verification level of an earlier AWS run.

## Decision

Part 5 Stage 1 stores its strict schema and validator under `release/part5/stage1` and its
self-digesting contract under `evidence/part5/stage1`. The contract binds:

- the exact annotated `v0.1.0` tag object and release commit;
- release receipt, deterministic archive, and post-release verification digests;
- managed workload run `33329861907`, recovery run `33328391707`, and clean-inventory run
  `33364428199`;
- the Stage 7 107-file runtime digest and its Stage 6 source;
- four committed Part 4 evidence authorities by file digest;
- the original engineering objectives and twelve mandatory completion gates; and
- the non-production, unsettled-billing, and non-sustained-operation claim boundaries.

The contract records that Part 5 completion equals project completion. It also fixes
`project_complete: false`, `all_part5_stages_complete: false`, and `remaining_work_required: true`
at the Stage 1 boundary. Later stages may satisfy the frozen gates, but cannot silently remove or
rename them.

CI validates the schema, contract self-digest, source evidence, annotated tag, frozen runtime,
documentation, repository layout, professional naming, and deterministic reconstruction. Tests
mutate claims, runtime identity, completion state, schema strictness, and unknown keys and require
fail-closed rejection.

## Claim boundary

Stage 1 is repository-only `LOCAL_VERIFIED` with `aws_execution: false`. It makes no new claim about
managed behaviour, production readiness, sustained operation, scale, or settled billing. The
production claim remains false, sustained operation remains unestablished, actual billed cost
remains `UNCLAIMED`, and project completion remains false.

## Failure behavior

An incorrect tag target or type, evidence mutation, runtime drift, schema weakening, contract
digest mismatch, completion-gate change, claim inflation, frozen-root change, missing CI control,
documentation gap, or professional naming violation fails closed. No failure may be resolved by
removing a gate or broadening the accepted contract.
