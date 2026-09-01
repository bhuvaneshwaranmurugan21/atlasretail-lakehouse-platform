"""Build, validate, archive, and verify final AtlasRetail project completion."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import struct
import subprocess
import zlib
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
from release.part5.stage4.completion_candidate import EVIDENCE as STAGE4_EVIDENCE
from release.part5.stage4.completion_candidate import load_object as load_stage4
from release.part5.stage4.completion_candidate import (
    validate_publication_authority as validate_stage4_publication,
)

ROOT = Path(__file__).resolve().parents[3]
SCHEMA = Path("release/part5/stage5/project-completion.schema.json")
POLICY = Path("release/part5/stage5/completion-policy.json")
STAGE4_EVIDENCE_MERGE_COMMIT = "7883a71eb2c6b756628ea7615485d0a8493449fd"
COMPLETION_VERSION = "0.2.0"
COMPLETION_TAG = "v0.2.0"
COMMIT_PATTERN = re.compile(r"^[0-9a-f]{40}$")
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
ALL_GAPS = [f"P5-GAP-{number:03d}" for number in range(1, 7)]
REQUIRED_JOBS = [
    "correctness",
    "glue-runtime-integration",
    "project-completion-readiness",
    "terraform",
]
AUTHORITY_FILES = {
    "part5-stage1": CONTRACT,
    "part5-stage2": STAGE2_EVIDENCE,
    "part5-stage3": STAGE3_EVIDENCE,
    "part5-stage4": STAGE4_EVIDENCE,
}


class ProjectCompletionError(ValueError):
    """Raised when final project-completion authority is incomplete or inflated."""


def fail(message: str) -> NoReturn:
    raise ProjectCompletionError(message)


def require(condition: bool, message: str) -> None:
    if not condition:
        fail(message)


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def load_object(path: Path) -> dict[str, Any]:
    try:
        value: object = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ProjectCompletionError(f"{path}: unreadable JSON: {error}") from error
    if not isinstance(value, dict):
        fail(f"{path}: expected a JSON object")
    return value


def _git(repository: Path, *arguments: str, binary: bool = False) -> str | bytes:
    try:
        completed = subprocess.run(
            ["git", *arguments],
            cwd=repository,
            check=True,
            capture_output=True,
        )
    except (OSError, subprocess.CalledProcessError) as error:
        raise ProjectCompletionError(f"git {' '.join(arguments)} failed") from error
    if binary:
        return completed.stdout
    return completed.stdout.decode().strip()


def require_commit(repository: Path, commit: str, label: str) -> None:
    require(COMMIT_PATTERN.fullmatch(commit) is not None, f"{label} is not a full commit")
    require(_git(repository, "rev-parse", f"{commit}^{{commit}}") == commit, f"{label} differs")


def require_ancestor(repository: Path, ancestor: str, descendant: str, message: str) -> None:
    completed = subprocess.run(
        ["git", "merge-base", "--is-ancestor", ancestor, descendant],
        cwd=repository,
        check=False,
        capture_output=True,
    )
    require(completed.returncode == 0, message)


def fixed_gzip(value: bytes) -> bytes:
    """Return deterministic gzip bytes with fixed headers."""

    compressor = zlib.compressobj(level=9, method=zlib.DEFLATED, wbits=-15)
    compressed = compressor.compress(value) + compressor.flush()
    header = b"\x1f\x8b\x08\x00\x00\x00\x00\x00\x02\xff"
    trailer = struct.pack("<II", zlib.crc32(value) & 0xFFFFFFFF, len(value) & 0xFFFFFFFF)
    return header + compressed + trailer


def build_completion_archive(repository: Path, commit: str) -> bytes:
    """Build the deterministic v0.2.0 source archive for one exact commit."""

    require_commit(repository, commit, "completion archive commit")
    archive = cast(
        bytes,
        _git(
            repository,
            "archive",
            "--format=tar",
            f"--prefix=atlasretail-lakehouse-platform-{COMPLETION_VERSION}/",
            commit,
            binary=True,
        ),
    )
    return fixed_gzip(archive)


def tracked_tree_sha256(repository: Path, commit: str) -> str:
    listing = cast(bytes, _git(repository, "ls-tree", "-r", "--full-tree", commit, binary=True))
    return sha256_bytes(listing)


def validate_predecessors(repository: Path) -> dict[str, Any]:
    """Validate every Stage 1-4 authority and return their immutable identities."""

    stage1 = load_contract(repository / CONTRACT)
    validate_contract(stage1, repository)
    stage2 = load_traceability(repository / STAGE2_EVIDENCE)
    validate_stage2_publication(stage2, repository)
    stage3 = load_handoff(repository / STAGE3_EVIDENCE)
    validate_stage3_publication(stage3, repository)
    stage4 = load_stage4(repository / STAGE4_EVIDENCE)
    validate_stage4_publication(stage4, repository)
    require(stage1["state"] == "CONTRACT_FROZEN", "Stage 1 state differs")
    require(stage2["state"] == "GAP_BASELINE_RECORDED", "Stage 2 state differs")
    require(stage3["state"] == "OPERATIONAL_HANDOFF_VERIFIED", "Stage 3 state differs")
    require(stage4["state"] == "COMPLETION_CANDIDATE_VERIFIED", "Stage 4 state differs")
    require(stage4["remaining_gap_ids"] == ["P5-GAP-001", "P5-GAP-002"], "Stage 4 gaps differ")
    require(stage4["project_completion"]["project_complete"] is False, "Stage 4 claim changed")
    runtime = stage4["runtime_equivalence"]
    require(runtime == stage1["runtime_equivalence"], "frozen runtime authority differs")
    return {
        "authority_sha256": {
            authority_id: sha256(repository / path)
            for authority_id, path in sorted(AUTHORITY_FILES.items())
        },
        "runtime_equivalence": runtime,
        "stage1": stage1,
        "stage2": stage2,
        "stage3": stage3,
        "stage4": stage4,
    }


def load_policy(repository: Path = ROOT) -> dict[str, Any]:
    return load_object(repository / POLICY)


def build_readiness(
    final_commit: str,
    run_id: int,
    run_attempt: int,
    repository: Path = ROOT,
) -> dict[str, Any]:
    """Build non-completion readiness during PR or in-progress main CI."""

    require_commit(repository, final_commit, "readiness commit")
    require_ancestor(
        repository,
        STAGE4_EVIDENCE_MERGE_COMMIT,
        final_commit,
        "readiness commit does not descend from Stage 4 evidence",
    )
    require(run_id > 0 and run_attempt > 0, "readiness workflow authority is invalid")
    predecessors = validate_predecessors(repository)
    payload: dict[str, Any] = {
        "actual_billed_cost_claim": "UNCLAIMED",
        "aws_execution": False,
        "claim_level": "LOCAL_VERIFIED",
        "completion_tag": COMPLETION_TAG,
        "final_commit": final_commit,
        "part": 5,
        "predecessor_authority_sha256": predecessors["authority_sha256"],
        "project": "AtlasRetail",
        "project_complete": False,
        "remaining_gap_ids": ["P5-GAP-001", "P5-GAP-002"],
        "required_ci_jobs": REQUIRED_JOBS,
        "run_attempt": run_attempt,
        "run_id": run_id,
        "schema_version": "1.0",
        "stage": 5,
        "state": "FINAL_ATTESTATION_READY",
    }
    return {**payload, "readiness_sha256": digest(payload)}


def _workflow_authority(
    final_commit: str,
    workflow_run: dict[str, Any],
    workflow_jobs: list[dict[str, Any]],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    run_id = workflow_run.get("id")
    run_attempt = workflow_run.get("run_attempt")
    expected_url = f"https://github.com/bhuvaneshwaranmurugan21/atlasretail-lakehouse-platform/actions/runs/{run_id}"
    require(isinstance(run_id, int) and run_id > 0, "final CI run ID is invalid")
    require(isinstance(run_attempt, int) and run_attempt > 0, "final CI attempt is invalid")
    require(workflow_run.get("event") == "push", "final CI event is not push")
    require(workflow_run.get("head_branch") == "main", "final CI branch is not main")
    require(workflow_run.get("head_sha") == final_commit, "final CI commit differs")
    require(workflow_run.get("status") == "completed", "final CI is not completed")
    require(workflow_run.get("conclusion") == "success", "final CI did not succeed")
    require(workflow_run.get("html_url") == expected_url, "final CI URL differs")
    observed: dict[str, dict[str, Any]] = {}
    for job in workflow_jobs:
        name = job.get("name")
        require(isinstance(name, str), "workflow job name is invalid")
        name_value = cast(str, name)
        require(name_value not in observed, f"duplicate workflow job: {name_value}")
        observed[name_value] = job
    require(set(observed) == set(REQUIRED_JOBS), "required final CI job coverage differs")
    job_results: list[dict[str, Any]] = []
    for name in REQUIRED_JOBS:
        job = observed[name]
        job_id = job.get("id")
        require(isinstance(job_id, int) and job_id > 0, f"{name}: job ID is invalid")
        require(job.get("status") == "completed", f"{name}: job is not completed")
        require(job.get("conclusion") == "success", f"{name}: job did not succeed")
        job_results.append(
            {"conclusion": "success", "id": job_id, "name": name, "status": "completed"}
        )
    return (
        {
            "conclusion": "success",
            "event": "push",
            "head_branch": "main",
            "head_sha": final_commit,
            "run_attempt": run_attempt,
            "run_id": run_id,
            "status": "completed",
            "url": expected_url,
        },
        job_results,
    )


def _gate_results(repository: Path) -> list[dict[str, Any]]:
    authority = {
        "all_part5_stages_complete": [
            "part5-stage1",
            "part5-stage2",
            "part5-stage3",
            "part5-stage4",
            "final-main-ci",
        ],
        "claim_boundaries_preserved": ["part5-stage1"],
        "clean_inventory_authority_preserved": ["part5-stage1", "part5-stage4"],
        "deterministic_recovery_authority_preserved": ["part5-stage1", "part5-stage4"],
        "final_main_ci_green": ["final-main-ci"],
        "frozen_runtime_preserved": ["part5-stage1", "part5-stage4"],
        "managed_workload_authority_preserved": ["part5-stage1", "part5-stage4"],
        "operational_handoff_verified": ["part5-stage3"],
        "professional_naming_verified": ["part5-stage4", "final-main-ci"],
        "release_integrity_preserved": ["part5-stage1", "part5-stage4", "completion-tag-contract"],
        "repository_quality_gates_green": ["part5-stage4", "final-main-ci"],
        "unresolved_critical_defects_absent": ["part5-stage4", "final-main-ci"],
    }
    return [
        {"authority_ids": authority[gate], "gate": gate, "result": "PASS"}
        for gate in load_policy(repository)["completion_gates"]
    ]


def _objective_results(repository: Path) -> list[dict[str, Any]]:
    authority = {
        "cross_table_consistency": ["part5-stage1", "part5-stage4"],
        "deterministic_failure_recovery": ["part5-stage1", "part5-stage4"],
        "evidence_attribution": ["part5-stage1", "part5-stage4", "final-main-ci"],
        "managed_aws_validation": ["part5-stage1", "part5-stage4"],
        "operational_handoff": ["part5-stage3"],
        "release_integrity": ["part5-stage1", "part5-stage4", "completion-tag-contract"],
        "repository_quality": ["part5-stage4", "final-main-ci"],
    }
    return [
        {"authority_ids": authority[objective], "objective": objective, "result": "PASS"}
        for objective in load_policy(repository)["original_objectives"]
    ]


def build_project_completion(
    final_commit: str,
    workflow_run: dict[str, Any],
    workflow_jobs: list[dict[str, Any]],
    repository: Path = ROOT,
) -> dict[str, Any]:
    """Build project completion only from a completed successful final main run."""

    require_commit(repository, final_commit, "final project commit")
    require(_git(repository, "rev-parse", "HEAD") == final_commit, "checkout is not final commit")
    require_ancestor(
        repository,
        STAGE4_EVIDENCE_MERGE_COMMIT,
        final_commit,
        "final project commit does not descend from Stage 4 evidence",
    )
    predecessors = validate_predecessors(repository)
    run_authority, job_results = _workflow_authority(final_commit, workflow_run, workflow_jobs)
    policy = load_policy(repository)
    archive_sha = sha256_bytes(build_completion_archive(repository, final_commit))
    payload: dict[str, Any] = {
        "actual_billed_cost_claim": "UNCLAIMED",
        "aws_execution": False,
        "claim_boundaries": policy["claim_boundaries"],
        "claim_level": "LOCAL_VERIFIED",
        "closed_gap_ids": ALL_GAPS,
        "completion_tag": {
            **policy["completion_tag"],
            "archive_sha256": archive_sha,
            "tag_target_commit": final_commit,
        },
        "evidence_type": "part5-stage5-project-completion",
        "final_source": {
            "commit": final_commit,
            "main_ci": run_authority,
            "tracked_tree_sha256": tracked_tree_sha256(repository, final_commit),
            "tree": _git(repository, "rev-parse", f"{final_commit}^{{tree}}"),
        },
        "gate_results": _gate_results(repository),
        "objective_results": _objective_results(repository),
        "part": 5,
        "predecessor_authority_sha256": predecessors["authority_sha256"],
        "project": "AtlasRetail",
        "project_completion": {
            "all_part5_stages_complete": True,
            "project_complete": True,
            "remaining_work_required": False,
        },
        "required_job_results": job_results,
        "runtime_equivalence": predecessors["runtime_equivalence"],
        "schema_sha256": sha256(repository / SCHEMA),
        "schema_version": "1.0",
        "stage": 5,
        "stage_results": policy["stage_states"],
        "state": "PROJECT_COMPLETION_VERIFIED",
    }
    return {**payload, "receipt_sha256": digest(payload)}


def validate_project_completion(receipt: dict[str, Any], repository: Path = ROOT) -> None:
    """Reject receipt drift, incomplete CI, missing gates, or claim inflation."""

    source = receipt.get("final_source")
    require(isinstance(source, dict), "final source is absent")
    source_value = cast(dict[str, Any], source)
    commit = source_value.get("commit")
    run = source_value.get("main_ci")
    jobs = receipt.get("required_job_results")
    require(isinstance(commit, str), "final commit is absent")
    require(isinstance(run, dict), "final main CI authority is absent")
    require(isinstance(jobs, list), "required job results are absent")
    commit_value = cast(str, commit)
    run_value = cast(dict[str, Any], run)
    jobs_value = cast(list[object], jobs)
    workflow_run = {
        "conclusion": run_value.get("conclusion"),
        "event": run_value.get("event"),
        "head_branch": run_value.get("head_branch"),
        "head_sha": run_value.get("head_sha"),
        "html_url": run_value.get("url"),
        "id": run_value.get("run_id"),
        "run_attempt": run_value.get("run_attempt"),
        "status": run_value.get("status"),
    }
    workflow_jobs = [cast(dict[str, Any], job) for job in jobs_value]
    expected = build_project_completion(commit_value, workflow_run, workflow_jobs, repository)
    require(set(receipt) == set(expected), "completion receipt keys differ")
    payload = dict(receipt)
    supplied = payload.pop("receipt_sha256")
    require(supplied == digest(payload), "completion receipt digest differs")
    expected_payload = dict(expected)
    expected_payload.pop("receipt_sha256")
    require(payload == expected_payload, "completion receipt values differ")
    require(receipt["closed_gap_ids"] == ALL_GAPS, "completion gap closure differs")
    require(receipt["project_completion"]["project_complete"] is True, "completion is false")
    require(receipt["aws_execution"] is False, "Stage 5 falsely claims AWS execution")


def build_post_completion_verification(
    repository: Path,
    tag: str,
    receipt_path: Path,
    archive_path: Path,
) -> dict[str, Any]:
    """Verify the annotated tag, external receipt, and reproducible final archive."""

    require(tag == COMPLETION_TAG, "completion tag differs")
    require(_git(repository, "cat-file", "-t", tag) == "tag", "completion tag is not annotated")
    target = cast(str, _git(repository, "rev-parse", f"{tag}^{{commit}}"))
    tag_object = cast(str, _git(repository, "rev-parse", tag))
    require(_git(repository, "rev-parse", "HEAD") == target, "checkout is not tag target")
    receipt = load_object(receipt_path)
    validate_project_completion(receipt, repository)
    require(receipt["final_source"]["commit"] == target, "receipt commit differs from tag")
    archive = archive_path.read_bytes()
    expected_archive = build_completion_archive(repository, target)
    require(archive == expected_archive, "completion archive is not reproducible")
    receipt_sha = sha256(receipt_path)
    archive_sha = sha256_bytes(archive)
    stage4_sha = sha256(repository / STAGE4_EVIDENCE)
    run_id = receipt["final_source"]["main_ci"]["run_id"]
    tag_text = cast(str, _git(repository, "cat-file", "-p", tag))
    required_lines = {
        f"Project-Completion-Commit: {target}",
        f"Final-Main-CI-Run-ID: {run_id}",
        f"Project-Completion-Receipt-SHA256: {receipt_sha}",
        f"Source-Archive-SHA256: {archive_sha}",
        f"Stage4-Receipt-SHA256: {stage4_sha}",
        "Signature-Claim: NOT_CLAIMED",
    }
    require(required_lines.issubset(set(tag_text.splitlines())), "tag annotation bindings differ")
    payload: dict[str, Any] = {
        "archive_sha256": archive_sha,
        "claim_level": "LOCAL_VERIFIED",
        "evidence_type": "part5-stage5-post-completion-verification",
        "final_main_ci_run_id": run_id,
        "project": "AtlasRetail",
        "project_complete": True,
        "receipt_file_sha256": receipt_sha,
        "receipt_sha256": receipt["receipt_sha256"],
        "result": "PASS",
        "schema_version": "1.0",
        "signature_claim": "NOT_CLAIMED",
        "tag": tag,
        "tag_object": tag_object,
        "tag_target_commit": target,
        "tag_type": "ANNOTATED",
    }
    return {**payload, "verification_sha256": digest(payload)}


def write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def write_bytes(path: Path, value: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_bytes(value)
    temporary.replace(path)


def _load_jobs(path: Path) -> list[dict[str, Any]]:
    value: object = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(value, dict):
        value = value.get("jobs")
    if not isinstance(value, list) or not all(isinstance(job, dict) for job in value):
        fail("workflow jobs JSON is invalid")
    return [cast(dict[str, Any], job) for job in value]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    readiness = commands.add_parser("readiness")
    readiness.add_argument("--final-commit", required=True)
    readiness.add_argument("--run-id", required=True, type=int)
    readiness.add_argument("--run-attempt", required=True, type=int)
    readiness.add_argument("--output", required=True, type=Path)
    build = commands.add_parser("build")
    build.add_argument("--final-commit", required=True)
    build.add_argument("--workflow-run", required=True, type=Path)
    build.add_argument("--workflow-jobs", required=True, type=Path)
    build.add_argument("--output", required=True, type=Path)
    verify = commands.add_parser("verify")
    verify.add_argument("--receipt", required=True, type=Path)
    archive = commands.add_parser("build-archive")
    archive.add_argument("--commit", required=True)
    archive.add_argument("--output", required=True, type=Path)
    verify_tag = commands.add_parser("verify-tag")
    verify_tag.add_argument("--tag", required=True)
    verify_tag.add_argument("--receipt", required=True, type=Path)
    verify_tag.add_argument("--archive", required=True, type=Path)
    verify_tag.add_argument("--output", required=True, type=Path)
    arguments = parser.parse_args()
    try:
        if arguments.command == "readiness":
            write_json(
                arguments.output,
                build_readiness(arguments.final_commit, arguments.run_id, arguments.run_attempt),
            )
        elif arguments.command == "build":
            write_json(
                arguments.output,
                build_project_completion(
                    arguments.final_commit,
                    load_object(arguments.workflow_run),
                    _load_jobs(arguments.workflow_jobs),
                ),
            )
        elif arguments.command == "verify":
            validate_project_completion(load_object(arguments.receipt))
        elif arguments.command == "build-archive":
            write_bytes(arguments.output, build_completion_archive(ROOT, arguments.commit))
        else:
            write_json(
                arguments.output,
                build_post_completion_verification(
                    ROOT,
                    arguments.tag,
                    arguments.receipt,
                    arguments.archive,
                ),
            )
    except (ProjectCompletionError, OSError, ValueError, subprocess.SubprocessError) as error:
        print(f"Part 5 Stage 5 project completion rejected: {error}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
