# Repository quality and completion-candidate audit

Part 5 Stage 4 evaluates one exact completion-candidate source. The audit is fail closed and closes
the repository-quality gaps only as a coupled set:

- `P5-GAP-004`: repository-wide professional naming verified.
- `P5-GAP-005`: source-exact repository quality gates green.
- `P5-GAP-006`: no unresolved critical or high defect remains.

`P5-GAP-003` was already closed by the verified Stage 3 operational handoff. `P5-GAP-001` and
`P5-GAP-002` remain blocking after Stage 4, so project completion remains false.

## Naming boundary

The candidate scan covers every Git-tracked path, every tracked file that decodes as UTF-8, and
every commit subject from the established naming-policy boundary through the controls merge.
Binary content is counted and disclosed rather than silently treated as scanned text. The Stage 4
receipt is excluded from the candidate-tree digest to avoid a self-referential receipt, but its
strict values and digest are validated independently.

The historical repository is not rewritten. That would invalidate the annotated `v0.1.0` release
and its checksum provenance. The defensible claim is the current completion-candidate tree and all
post-policy commit subjects.

## Source-exact quality gates

The quality policy binds sixteen check groups:

1. Ruff lint and formatting plus strict mypy.
2. The full test suite and minimum 85% coverage.
3. Part 4 contracts and deterministic source provenance.
4. Every Part 4 control through release integrity.
5. Every Part 5 control through Stage 4.
6. Frozen Stage 7 runtime equivalence.
7. CloudFormation lint in `ap-southeast-2`.
8. Python compilation.
9. Shell syntax.
10. Byte-identical deterministic source reproduction.
11. Byte-identical deterministic Stage 4 control reproduction.
12. Professional naming.
13. Immutable external action references.
14. Tracked-tree sensitive-material scanning.
15. Glue 5-compatible Spark and Iceberg integration.
16. Terraform format and backend-free validation.

The final `COMPLETION_CANDIDATE_VERIFIED` receipt binds the controls merge and successful `main` CI
run that executes these checks. A skipped, removed, mutable, or failing check prevents publication.

## Defect audit

The policy requires complete coverage of contract/schema, transformation correctness, data
quality, publication consistency, recovery/teardown, infrastructure/IAM, CI reproducibility,
evidence provenance, claim boundaries, documentation/naming, repository hygiene, and managed
runtime. Every domain maps to explicit quality-check evidence.

Critical and high findings must be resolved. They cannot be accepted as limitations. Two honest
claim boundaries remain documented as lower-severity accepted limitations: the bounded workload
does not establish production scale or sustained operation, and settled billing remains outside
the durable evidence. Actual billed cost remains `UNCLAIMED`.

## Publication boundary

The controls pull request produces `COMPLETION_CANDIDATE_CONTROLS_READY`. After its manual merge and
successful `main` CI, a separate evidence-only pull request records the deterministic receipt. No
AWS operation occurs in either change. Frozen runtime and managed authorities remain unchanged.
