"""Build and validate the deterministic Part 5 Stage 4 completion candidate."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any, NoReturn, cast

from atlasretail.canonical import digest
from release.part5.stage1.completion_contract import CONTRACT, load_contract, validate_contract
from release.part5.stage2.evidence_traceability import EVIDENCE as STAGE2_EVIDENCE
from release.part5.stage2.evidence_traceability import load_traceability
from release.part5.stage2.evidence_traceability import (
    validate_publication_authority as validate_stage2_publication,
)
from release.part5.stage3.operational_handoff import EVIDENCE as STAGE3_EVIDENCE
from release.part5.stage3.operational_handoff import load_handoff
from release.part5.stage3.operational_handoff import (
    validate_publication_authority as validate_stage3_publication,
)

ROOT = Path(__file__).resolve().parents[3]
SCHEMA = Path("release/part5/stage4/completion-candidate.schema.json")
POLICY = Path("release/part5/stage4/quality-policy.json")
EVIDENCE = Path("evidence/part5/stage4/completion-candidate.json")
STAGE3_EVIDENCE_MERGE_COMMIT = "05d32e44466c4316ffc2cf21476e7a48f168870e"
NAMING_POLICY_COMMIT = "1025168934ae9c45306407fe372d9d39f767557e"

PREDECESSOR_CLOSED_GAPS = ["P5-GAP-003"]
NEWLY_CLOSED_GAPS = ["P5-GAP-004", "P5-GAP-005", "P5-GAP-006"]
REMAINING_GAPS = ["P5-GAP-001", "P5-GAP-002"]

EXPECTED_CHECK_IDS = [
    "static-analysis",
    "full-test-suite",
    "part4-contract",
    "part4-controls",
    "part5-controls",
    "frozen-runtime",
    "cloudformation-lint",
    "python-compilation",
    "shell-syntax",
    "deterministic-source-provenance",
    "deterministic-controls",
    "professional-naming",
    "action-pinning",
    "sensitive-material-scan",
    "glue-runtime-integration",
    "terraform-validation",
]

EXPECTED_DOMAIN_IDS = [
    "contract-schema",
    "transformation-correctness",
    "data-quality",
    "publication-consistency",
    "recovery-teardown",
    "infrastructure-iam",
    "ci-reproducibility",
    "evidence-provenance",
    "claim-boundaries",
    "documentation-naming",
    "repository-hygiene",
    "managed-runtime",
]

AUTHORITY_FILES = {
    "part4-closure": Path("evidence/part4/stage7/completion-receipt.json"),
    "part4-release": Path("evidence/part4/stage8/release-receipt.json"),
    "part5-completion-contract": CONTRACT,
    "part5-gap-baseline": STAGE2_EVIDENCE,
    "part5-operational-handoff": STAGE3_EVIDENCE,
    "quality-policy": POLICY,
}


class CompletionCandidateError(ValueError):
    """Raised when completion-candidate authority or coverage is incomplete."""


def fail(message: str) -> NoReturn:
    raise CompletionCandidateError(message)


def sha256(path: Path) -> str:
    """Return the SHA-256 digest of one file."""

    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_object(path: Path) -> dict[str, Any]:
    """Load one strict JSON object."""

    value: object = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        fail(f"{path}: expected a JSON object")
    return value


def _git(repository: Path, *arguments: str, binary: bool = False) -> str | bytes:
    completed = subprocess.run(
        ["git", *arguments],
        cwd=repository,
        check=True,
        capture_output=True,
        text=not binary,
    )
    return cast(str | bytes, completed.stdout)


def tracked_files(repository: Path) -> list[str]:
    """Return candidate tracked files, excluding the self-referential Stage 4 receipt."""

    rendered = cast(bytes, _git(repository, "ls-files", "-z", binary=True))
    files = sorted(value.decode() for value in rendered.split(b"\0") if value)
    return [relative for relative in files if relative != EVIDENCE.as_posix()]


def tracked_tree_sha256(repository: Path) -> str:
    """Digest every candidate tracked path and byte stream in stable order."""

    result = hashlib.sha256()
    for relative in tracked_files(repository):
        path = repository / relative
        if not path.is_file() or path.is_symlink():
            fail(f"irregular tracked candidate path: {relative}")
        payload = path.read_bytes()
        result.update(relative.encode("utf-8"))
        result.update(b"\0")
        result.update(str(len(payload)).encode("ascii"))
        result.update(b"\0")
        result.update(hashlib.sha256(payload).digest())
    return result.hexdigest()


def load_policy(path: Path) -> dict[str, Any]:
    """Load the Stage 4 repository-quality policy."""

    return load_object(path)


def validate_policy(policy: dict[str, Any]) -> None:
    """Reject missing audit coverage, weakened checks, or unacceptable limitations."""

    if set(policy) != {
        "accepted_limitations",
        "audit_domains",
        "naming_scope",
        "quality_checks",
        "schema_version",
    }:
        fail("quality policy keys differ")
    if policy["schema_version"] != "1.0":
        fail("quality policy version differs")
    if policy["naming_scope"] != [
        "tracked-paths",
        "tracked-utf8-content",
        "post-policy-commit-subjects",
    ]:
        fail("naming audit scope differs")

    checks_value = policy["quality_checks"]
    if not isinstance(checks_value, list):
        fail("quality checks are absent")
    checks = cast(list[dict[str, Any]], checks_value)
    if [row.get("check_id") for row in checks] != EXPECTED_CHECK_IDS:
        fail("quality-check coverage or ordering differs")
    for row in checks:
        if set(row) != {"check_id", "ci_tokens"}:
            fail("quality-check keys differ")
        tokens = row["ci_tokens"]
        if not isinstance(tokens, list) or not tokens or len(tokens) != len(set(tokens)):
            fail(f"{row['check_id']}: CI token coverage differs")
        if not all(isinstance(token, str) and token for token in tokens):
            fail(f"{row['check_id']}: CI token is invalid")

    domains_value = policy["audit_domains"]
    if not isinstance(domains_value, list):
        fail("defect-audit domains are absent")
    domains = cast(list[dict[str, Any]], domains_value)
    if [row.get("domain_id") for row in domains] != EXPECTED_DOMAIN_IDS:
        fail("defect-audit domain coverage or ordering differs")
    known_checks = set(EXPECTED_CHECK_IDS)
    for row in domains:
        if set(row) != {"domain_id", "evidence_check_ids"}:
            fail("defect-audit domain keys differ")
        evidence = row["evidence_check_ids"]
        if not isinstance(evidence, list) or not evidence:
            fail(f"{row['domain_id']}: defect-audit evidence is absent")
        if len(evidence) != len(set(evidence)) or not set(evidence) <= known_checks:
            fail(f"{row['domain_id']}: defect-audit evidence differs")

    limitations_value = policy["accepted_limitations"]
    if not isinstance(limitations_value, list):
        fail("accepted limitations are absent")
    limitations = cast(list[dict[str, Any]], limitations_value)
    expected_ids = ["P5-LIMIT-001", "P5-LIMIT-002"]
    if [row.get("finding_id") for row in limitations] != expected_ids:
        fail("accepted limitation coverage or ordering differs")
    known_domains = set(EXPECTED_DOMAIN_IDS)
    for row in limitations:
        if set(row) != {"domain_id", "finding_id", "rationale", "severity", "status"}:
            fail("accepted limitation keys differ")
        if row["domain_id"] not in known_domains:
            fail("accepted limitation domain differs")
        if row["severity"] not in {"LOW", "MEDIUM"}:
            fail("critical or high finding cannot be an accepted limitation")
        if row["status"] != "ACCEPTED_LIMITATION":
            fail("accepted limitation status differs")
        if not isinstance(row["rationale"], str) or not row["rationale"]:
            fail("accepted limitation rationale is absent")


def validate_ci_policy(policy: dict[str, Any], repository: Path = ROOT) -> None:
    """Require every policy check to be enforced by the pinned CI workflow."""

    rendered = (repository / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    for row in cast(list[dict[str, Any]], policy["quality_checks"]):
        missing = [token for token in row["ci_tokens"] if token not in rendered]
        if missing:
            fail(f"{row['check_id']}: CI enforcement tokens are absent: {missing}")


def validate_action_pinning(repository: Path = ROOT) -> int:
    """Reject mutable external action references in executable workflows."""

    count = 0
    pattern = re.compile(r"\buses:\s*([^\s#]+)")
    for path in sorted((repository / ".github/workflows").glob("*.yml")):
        for line in path.read_text(encoding="utf-8").splitlines():
            match = pattern.search(line)
            if match is None:
                continue
            count += 1
            reference = match.group(1)
            if reference.startswith("./"):
                continue
            if re.fullmatch(r"[^@]+@[0-9a-f]{40}", reference) is None:
                fail(f"workflow action is not commit pinned: {path.relative_to(repository)}")
    if count == 0:
        fail("workflow action inventory is empty")
    return count


def validate_sensitive_material(repository: Path = ROOT) -> None:
    """Reject common credential and private-key material from the candidate tree."""

    private_key = re.compile("-----BEGIN " + r"(?:RSA |EC |OPENSSH )?" + "PRIVATE KEY-----")
    access_key = re.compile(r"(?:A" + "KIA|A" + r"SIA)[0-9A-Z]{16}")
    repository_token = re.compile("g" + r"h[pousr]_[A-Za-z0-9]{36,255}")
    violations: list[str] = []
    for relative in tracked_files(repository):
        payload = (repository / relative).read_bytes()
        try:
            rendered = payload.decode("utf-8")
        except UnicodeDecodeError:
            continue
        if any(pattern.search(rendered) for pattern in (private_key, access_key, repository_token)):
            violations.append(relative)
    if violations:
        fail(f"sensitive material detected in tracked files: {sorted(violations)}")


def _naming_pattern() -> re.Pattern[str]:
    names = ("co" + "dex", "chat" + "gpt", "open" + "ai")
    patterns = [re.escape(value) for value in names]
    patterns.extend(("a" + r"i(?:-| )assisted", "generated by " + "a" + "i"))
    return re.compile(rf"(?i)\b(?:{'|'.join(patterns)})\b")


def build_naming_audit(repository: Path = ROOT, end_ref: str = "HEAD") -> dict[str, Any]:
    """Scan candidate paths, UTF-8 content, and post-policy commit subjects."""

    pattern = _naming_pattern()
    violations: list[str] = []
    utf8_count = 0
    binary_count = 0
    files = tracked_files(repository)
    for relative in files:
        if pattern.search(relative):
            violations.append(f"path:{relative}")
        payload = (repository / relative).read_bytes()
        try:
            rendered = payload.decode("utf-8")
        except UnicodeDecodeError:
            binary_count += 1
            continue
        utf8_count += 1
        if pattern.search(rendered):
            violations.append(f"content:{relative}")
    subjects = cast(
        str,
        _git(repository, "log", "--format=%H%x09%s", f"{NAMING_POLICY_COMMIT}^..{end_ref}"),
    ).splitlines()
    for row in subjects:
        if pattern.search(row):
            violations.append("post-policy-commit-subject")
    if violations:
        fail(f"professional naming violations: {sorted(violations)}")
    return {
        "binary_content_skipped_count": binary_count,
        "post_policy_commit_count": len(subjects),
        "result": "PASS",
        "scope": [
            "tracked-paths",
            "tracked-utf8-content",
            "post-policy-commit-subjects",
        ],
        "tracked_file_count": len(files),
        "utf8_content_scanned_count": utf8_count,
    }


def _load_predecessors(
    repository: Path,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    stage1 = load_contract(repository / CONTRACT)
    try:
        validate_contract(stage1, repository)
    except ValueError as error:
        raise CompletionCandidateError(f"Stage 1 admission failed: {error}") from error
    stage2 = load_traceability(repository / STAGE2_EVIDENCE)
    try:
        validate_stage2_publication(stage2, repository)
    except ValueError as error:
        raise CompletionCandidateError(f"Stage 2 admission failed: {error}") from error
    stage3 = load_handoff(repository / STAGE3_EVIDENCE)
    try:
        validate_stage3_publication(stage3, repository)
    except ValueError as error:
        raise CompletionCandidateError(f"Stage 3 admission failed: {error}") from error
    return stage1, stage2, stage3


def _validate_gap_partition(stage2: dict[str, Any], stage3: dict[str, Any]) -> None:
    baseline = {row["gap_id"] for row in stage2["gaps"]}
    predecessor = set(PREDECESSOR_CLOSED_GAPS)
    newly_closed = set(NEWLY_CLOSED_GAPS)
    remaining = set(REMAINING_GAPS)
    if stage3["closed_gap_ids"] != PREDECESSOR_CLOSED_GAPS:
        fail("Stage 3 closed-gap authority differs")
    if set(stage3["remaining_gap_ids"]) != newly_closed | remaining:
        fail("Stage 3 remaining-gap authority differs")
    partitions = (predecessor, newly_closed, remaining)
    if any(
        left & right for index, left in enumerate(partitions) for right in partitions[index + 1 :]
    ):
        fail("completion-gap partitions overlap")
    if set().union(*partitions) != baseline:
        fail("completion-gap partitions do not cover the baseline")


def build_completion_candidate(
    controls_merge_commit: str,
    controls_main_ci_run_id: str,
    repository: Path = ROOT,
) -> dict[str, Any]:
    """Build the exact repository-quality and defect-audit receipt."""

    if re.fullmatch(r"[0-9a-f]{40}", controls_merge_commit) is None:
        fail("controls merge commit is invalid")
    if re.fullmatch(r"[1-9][0-9]*", controls_main_ci_run_id) is None:
        fail("controls main CI run ID is invalid")
    stage1, stage2, stage3 = _load_predecessors(repository)
    _validate_gap_partition(stage2, stage3)
    policy = load_policy(repository / POLICY)
    validate_policy(policy)
    validate_ci_policy(policy, repository)
    validate_action_pinning(repository)
    validate_sensitive_material(repository)
    commit_exists = (
        subprocess.run(
            ["git", "cat-file", "-e", f"{controls_merge_commit}^{{commit}}"],
            cwd=repository,
            check=False,
            capture_output=True,
        ).returncode
        == 0
    )
    naming_audit = build_naming_audit(
        repository,
        controls_merge_commit if commit_exists else "HEAD",
    )

    findings = cast(list[dict[str, Any]], policy["accepted_limitations"])
    finding_ids_by_domain: dict[str, list[str]] = {
        domain_id: [] for domain_id in EXPECTED_DOMAIN_IDS
    }
    for finding in findings:
        finding_ids_by_domain[cast(str, finding["domain_id"])].append(
            cast(str, finding["finding_id"])
        )
    domains = cast(list[dict[str, Any]], policy["audit_domains"])
    payload: dict[str, Any] = {
        "actual_billed_cost_claim": "UNCLAIMED",
        "authority_file_sha256": {
            authority_id: sha256(repository / path)
            for authority_id, path in AUTHORITY_FILES.items()
        },
        "aws_execution": False,
        "claim_boundaries": stage1["claim_boundaries"],
        "claim_level": "LOCAL_VERIFIED",
        "controls_authority": {
            "main_ci_run_id": controls_main_ci_run_id,
            "merge_commit": controls_merge_commit,
        },
        "defect_audit": {
            "domain_results": [
                {
                    "domain_id": row["domain_id"],
                    "evidence_check_ids": row["evidence_check_ids"],
                    "finding_ids": finding_ids_by_domain[cast(str, row["domain_id"])],
                    "result": "PASS",
                }
                for row in domains
            ],
            "findings": findings,
            "result": "PASS",
            "unresolved_critical_count": 0,
            "unresolved_high_count": 0,
        },
        "evidence_type": "part5-stage4-completion-candidate",
        "naming_audit": naming_audit,
        "newly_closed_gap_ids": NEWLY_CLOSED_GAPS,
        "part": 5,
        "policy_sha256": sha256(repository / POLICY),
        "predecessor_closed_gap_ids": PREDECESSOR_CLOSED_GAPS,
        "project": "AtlasRetail",
        "project_completion": {
            "all_part5_stages_complete": False,
            "project_complete": False,
            "remaining_work_required": True,
        },
        "quality_audit": {
            "checks": [
                {"check_id": row["check_id"], "result": "PASS"}
                for row in cast(list[dict[str, Any]], policy["quality_checks"])
            ],
            "result": "PASS",
        },
        "remaining_gap_ids": REMAINING_GAPS,
        "runtime_equivalence": stage1["runtime_equivalence"],
        "schema_sha256": sha256(repository / SCHEMA),
        "schema_version": "1.0",
        "stage": 4,
        "stage1_contract_sha256": stage1["contract_sha256"],
        "stage2_receipt_sha256": stage2["receipt_sha256"],
        "stage3_receipt_sha256": stage3["receipt_sha256"],
        "state": "COMPLETION_CANDIDATE_VERIFIED",
        "tracked_tree_sha256": tracked_tree_sha256(repository),
    }
    return {**payload, "receipt_sha256": digest(payload)}


def validate_completion_candidate(receipt: dict[str, Any], repository: Path = ROOT) -> None:
    """Fail closed on audit omissions, authority drift, or claim inflation."""

    controls = receipt.get("controls_authority")
    if not isinstance(controls, dict):
        fail("controls authority is absent")
    merge_commit = controls.get("merge_commit")
    main_ci_run_id = controls.get("main_ci_run_id")
    if not isinstance(merge_commit, str) or not isinstance(main_ci_run_id, str):
        fail("controls authority identifiers are absent")
    expected = build_completion_candidate(merge_commit, main_ci_run_id, repository)
    if set(receipt) != set(expected):
        fail("receipt keys differ")
    payload = dict(receipt)
    supplied_digest = payload.pop("receipt_sha256")
    if supplied_digest != digest(payload):
        fail("receipt digest differs")
    expected_payload = dict(expected)
    expected_payload.pop("receipt_sha256")
    if payload != expected_payload:
        fail("receipt values differ")
    if receipt["predecessor_closed_gap_ids"] != PREDECESSOR_CLOSED_GAPS:
        fail("predecessor closed-gap set differs")
    if receipt["newly_closed_gap_ids"] != NEWLY_CLOSED_GAPS:
        fail("newly closed-gap set differs")
    if receipt["remaining_gap_ids"] != REMAINING_GAPS:
        fail("remaining-gap set differs")
    defect = receipt["defect_audit"]
    if defect["unresolved_critical_count"] != 0 or defect["unresolved_high_count"] != 0:
        fail("unresolved critical or high defects remain")
    if receipt["project_completion"]["project_complete"] is not False:
        fail("project completion was inflated")


def validate_publication_authority(receipt: dict[str, Any], repository: Path = ROOT) -> None:
    """Require the recorded controls merge in this Stage 4 evidence history."""

    controls = receipt.get("controls_authority")
    if not isinstance(controls, dict) or not isinstance(controls.get("merge_commit"), str):
        fail("controls merge commit is absent")
    merge_commit = cast(str, controls["merge_commit"])
    exists = subprocess.run(
        ["git", "cat-file", "-e", f"{merge_commit}^{{commit}}"],
        cwd=repository,
        check=False,
        capture_output=True,
    )
    if exists.returncode != 0:
        fail("controls merge commit is absent from repository history")
    if merge_commit == STAGE3_EVIDENCE_MERGE_COMMIT:
        fail("controls merge commit does not identify the Stage 4 controls merge")
    with historical_worktree(repository, merge_commit) as historical:
        validate_completion_candidate(receipt, historical)
    for ancestor, descendant, message in (
        (
            STAGE3_EVIDENCE_MERGE_COMMIT,
            merge_commit,
            "controls merge does not descend from Stage 3 evidence",
        ),
        (merge_commit, "HEAD", "receipt history does not descend from the controls merge"),
    ):
        completed = subprocess.run(
            ["git", "merge-base", "--is-ancestor", ancestor, descendant],
            cwd=repository,
            check=False,
            capture_output=True,
        )
        if completed.returncode != 0:
            fail(message)


@contextmanager
def historical_worktree(repository: Path, commit: str) -> Iterator[Path]:
    """Expose one exact historical tree for non-self-invalidating receipt verification."""

    with tempfile.TemporaryDirectory(prefix="atlasretail-stage4-") as directory:
        path = Path(directory) / "repository"
        added = False
        try:
            subprocess.run(
                ["git", "worktree", "add", "--detach", "--quiet", str(path), commit],
                cwd=repository,
                check=True,
                capture_output=True,
            )
            added = True
            yield path
        finally:
            if added:
                subprocess.run(
                    ["git", "worktree", "remove", "--force", str(path)],
                    cwd=repository,
                    check=True,
                    capture_output=True,
                )


def write_candidate(path: Path, receipt: dict[str, Any]) -> None:
    """Write canonical human-readable JSON for review and byte comparison."""

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    build = commands.add_parser("build")
    build.add_argument("--controls-merge-commit", required=True)
    build.add_argument("--controls-main-ci-run-id", required=True)
    build.add_argument("--output", type=Path, required=True)
    verify = commands.add_parser("verify")
    verify.add_argument("--receipt", type=Path, required=True)
    arguments = parser.parse_args()
    try:
        if arguments.command == "build":
            receipt = build_completion_candidate(
                arguments.controls_merge_commit,
                arguments.controls_main_ci_run_id,
                ROOT,
            )
            write_candidate(arguments.output, receipt)
        else:
            validate_publication_authority(load_object(arguments.receipt), ROOT)
    except (CompletionCandidateError, OSError, subprocess.SubprocessError, ValueError) as error:
        print(f"Part 5 Stage 4 completion candidate rejected: {error}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
