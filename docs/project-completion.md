# AtlasRetail project-completion procedure

Part 5 Stage 5 is the terminal AtlasRetail project stage. Its controls prepare the final
attestation but do not make the completion claim inside the pull request.

## Immutable inputs

- Stage 1 contract state: `CONTRACT_FROZEN`
- Stage 2 traceability state: `GAP_BASELINE_RECORDED`
- Stage 3 handoff state: `OPERATIONAL_HANDOFF_VERIFIED`
- Stage 4 candidate state: `COMPLETION_CANDIDATE_VERIFIED`
- Frozen managed surface: 107 files with SHA-256
  `2e1d10c936c23637929e65589fab324c4a2602b98da283135527733ea26f1e38`
- Completion version and annotated tag: `v0.2.0`
- Required final jobs: `correctness`, `glue-runtime-integration`,
  `project-completion-readiness`, and `terraform`

## Before the final merge

Run the complete source-exact suite:

```bash
python -m release.part5.stage5.validate_controls
python -m pytest --cov-fail-under=85
python -m ruff check .
python -m ruff format --check .
python -m mypy src release/part4/stage8 release/part5/stage1 \
  release/part5/stage2 release/part5/stage3 release/part5/stage4 release/part5/stage5
```

CI must produce deterministic Stage 5 control and readiness artifacts. Readiness state is
`FINAL_ATTESTATION_READY`; project completion remains false, `P5-GAP-001` and `P5-GAP-002` remain
open, Stage 5 performs no AWS operation, and actual billed cost remains `UNCLAIMED`.

## After the final merge

1. Resolve the exact `origin/main` commit and require a clean detached checkout of it.
2. Identify the completed successful `push` workflow run whose `head_branch` is `main` and whose
   `head_sha` is the exact final commit.
3. Retrieve every job for that run. Require exactly the four named jobs, each completed with
   conclusion `success`.
4. Re-run Stage 1 through Stage 5 validators from the final commit.
5. Build the deterministic source archive with `project_completion build-archive`.
6. Build the external completion receipt with `project_completion build`. The builder rejects any
   source/run/job mismatch.
7. Re-run `project_completion verify` against the receipt.
8. Create annotated tag `v0.2.0` with the mandatory digest and authority bindings.
9. Verify the annotated tag and archive with `project_completion verify-tag`.
10. Publish a GitHub release from the existing tag. Attach the deterministic source archive,
    project-completion receipt, post-completion verification record, and a SHA-256 checksum file.
11. Download the published assets into a clean directory, verify their checksums, and reproduce
    the tag verification once more.

Only after steps 1 through 11 pass may the receipt state be `PROJECT_COMPLETION_VERIFIED`, all six
Part 5 gaps be closed, `all_part5_stages_complete` be true, and `remaining_work_required` be false.

## Failure handling

Stop without creating or moving the tag when any commit, tree, workflow, job, digest, predecessor,
archive, or annotation value differs. Fix the root cause in a new repository change and repeat the
final merge and final-main validation. Never edit a completion receipt, weaken a required job,
replace the annotated tag with a lightweight tag, or reuse evidence from a different commit.

The completion claim is an engineering-delivery claim. Production readiness remains
`NOT_CLAIMED`, sustained operation remains `NOT_ESTABLISHED`, tag-signature verification remains
`NOT_CLAIMED`, and actual billed cost remains `UNCLAIMED`.
