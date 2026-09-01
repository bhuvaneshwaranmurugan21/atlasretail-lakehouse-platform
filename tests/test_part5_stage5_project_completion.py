from __future__ import annotations

import copy
import gzip
import io
import json
import subprocess
import tarfile
from pathlib import Path

import pytest

from release.part5.stage5.project_completion import (
    ALL_GAPS,
    COMPLETION_TAG,
    POLICY,
    REQUIRED_JOBS,
    SCHEMA,
    ProjectCompletionError,
    build_completion_archive,
    build_post_completion_verification,
    build_project_completion,
    build_readiness,
    load_policy,
    sha256,
    sha256_bytes,
    validate_project_completion,
)
from release.part5.stage5.validate_controls import ControlsError, validate, validate_schema

ROOT = Path(__file__).resolve().parents[1]


def _head(repository: Path = ROOT) -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repository,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _workflow(commit: str) -> tuple[dict[str, object], list[dict[str, object]]]:
    run_id = 41000000001
    run = {
        "conclusion": "success",
        "event": "push",
        "head_branch": "main",
        "head_sha": commit,
        "html_url": (
            "https://github.com/bhuvaneshwaranmurugan21/"
            f"atlasretail-lakehouse-platform/actions/runs/{run_id}"
        ),
        "id": run_id,
        "run_attempt": 1,
        "status": "completed",
    }
    jobs = [
        {
            "conclusion": "success",
            "id": run_id + index + 1,
            "name": name,
            "status": "completed",
        }
        for index, name in enumerate(REQUIRED_JOBS)
    ]
    return run, jobs


def _receipt(repository: Path = ROOT) -> dict[str, object]:
    commit = _head(repository)
    run, jobs = _workflow(commit)
    return build_project_completion(commit, run, jobs, repository)


def _clone(tmp_path: Path) -> Path:
    repository = tmp_path / "repository"
    subprocess.run(
        ["git", "clone", "--quiet", "--no-local", str(ROOT), str(repository)],
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "AtlasRetail Release"],
        cwd=repository,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.email", "release@atlasretail.example"],
        cwd=repository,
        check=True,
    )
    return repository


def _write_json(path: Path, value: dict[str, object]) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _tag_message(repository: Path, receipt_path: Path, archive_path: Path) -> str:
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    commit = receipt["final_source"]["commit"]
    run_id = receipt["final_source"]["main_ci"]["run_id"]
    stage4 = repository / "evidence/part5/stage4/completion-candidate.json"
    return "\n".join(
        [
            "AtlasRetail project completion v0.2.0",
            "",
            f"Project-Completion-Commit: {commit}",
            f"Final-Main-CI-Run-ID: {run_id}",
            f"Project-Completion-Receipt-SHA256: {sha256(receipt_path)}",
            f"Source-Archive-SHA256: {sha256(archive_path)}",
            f"Stage4-Receipt-SHA256: {sha256(stage4)}",
            "Signature-Claim: NOT_CLAIMED",
        ]
    )


def test_stage5_controls_are_deterministic_non_completion() -> None:
    first = validate(ROOT)
    second = validate(ROOT)
    assert first == second
    assert first["result"] == "PASS"
    assert first["state"] == "PROJECT_COMPLETION_CONTROLS_READY"
    assert first["project_complete"] is False
    assert first["remaining_gap_ids"] == ["P5-GAP-001", "P5-GAP-002"]
    assert first["aws_execution"] is False


def test_readiness_is_deterministic_and_cannot_claim_completion() -> None:
    commit = _head()
    first = build_readiness(commit, 71, 1, ROOT)
    second = build_readiness(commit, 71, 1, ROOT)
    assert first == second
    assert first["state"] == "FINAL_ATTESTATION_READY"
    assert first["project_complete"] is False
    assert first["remaining_gap_ids"] == ["P5-GAP-001", "P5-GAP-002"]


def test_policy_freezes_all_gaps_gates_objectives_jobs_and_tag() -> None:
    policy = load_policy(ROOT)
    assert policy["closed_gap_ids"] == ALL_GAPS
    assert len(policy["completion_gates"]) == 12
    assert len(policy["original_objectives"]) == 7
    assert len(policy["stage_states"]) == 5
    assert policy["required_ci_jobs"] == REQUIRED_JOBS
    assert policy["completion_tag"]["tag"] == COMPLETION_TAG
    assert policy["completion_tag"]["tag_type"] == "ANNOTATED"
    assert policy["completion_tag"]["completion_version"] == "0.2.0"


def test_completion_receipt_is_deterministic_and_strict() -> None:
    first = _receipt()
    second = _receipt()
    assert first == second
    validate_project_completion(first, ROOT)
    assert first["state"] == "PROJECT_COMPLETION_VERIFIED"
    assert first["closed_gap_ids"] == ALL_GAPS
    assert first["project_completion"] == {
        "all_part5_stages_complete": True,
        "project_complete": True,
        "remaining_work_required": False,
    }
    assert first["aws_execution"] is False


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("event", "pull_request", "event is not push"),
        ("head_branch", "feature", "branch is not main"),
        ("status", "in_progress", "is not completed"),
        ("conclusion", "failure", "did not succeed"),
    ],
)
def test_completion_rejects_non_final_workflow(field: str, value: str, message: str) -> None:
    commit = _head()
    run, jobs = _workflow(commit)
    run[field] = value
    with pytest.raises(ProjectCompletionError, match=message):
        build_project_completion(commit, run, jobs, ROOT)


def test_completion_rejects_wrong_commit_or_job_coverage() -> None:
    commit = _head()
    run, jobs = _workflow(commit)
    run["head_sha"] = "0" * 40
    with pytest.raises(ProjectCompletionError, match="commit differs"):
        build_project_completion(commit, run, jobs, ROOT)
    run, jobs = _workflow(commit)
    with pytest.raises(ProjectCompletionError, match="job coverage differs"):
        build_project_completion(commit, run, jobs[:-1], ROOT)
    run, jobs = _workflow(commit)
    jobs[0]["conclusion"] = "skipped"
    with pytest.raises(ProjectCompletionError, match="did not succeed"):
        build_project_completion(commit, run, jobs, ROOT)


def test_receipt_rejects_mutation_and_unknown_keys() -> None:
    receipt = _receipt()
    mutated = copy.deepcopy(receipt)
    mutated["closed_gap_ids"] = ALL_GAPS[:-1]
    with pytest.raises(ProjectCompletionError):
        validate_project_completion(mutated, ROOT)
    unknown = copy.deepcopy(receipt)
    unknown["unexpected"] = True
    with pytest.raises(ProjectCompletionError, match="keys differ"):
        validate_project_completion(unknown, ROOT)


def test_schema_rejects_unknown_property_permission(tmp_path: Path) -> None:
    schema = json.loads((ROOT / SCHEMA).read_text(encoding="utf-8"))
    schema["additionalProperties"] = True
    path = tmp_path / "project-completion.schema.json"
    path.write_text(json.dumps(schema), encoding="utf-8")
    with pytest.raises(ControlsError, match="permits unknown keys"):
        validate_schema(path)


def test_completion_archive_is_deterministic_and_versioned() -> None:
    commit = _head()
    first = build_completion_archive(ROOT, commit)
    second = build_completion_archive(ROOT, commit)
    assert first == second
    assert sha256_bytes(first) == sha256_bytes(second)
    with tarfile.open(fileobj=io.BytesIO(gzip.decompress(first)), mode="r:") as archive:
        names = archive.getnames()
    assert names
    prefix = "atlasretail-lakehouse-platform-0.2.0"
    assert all(name == prefix or name.startswith(f"{prefix}/") for name in names)


def test_annotated_tag_and_archive_bindings_are_verified(tmp_path: Path) -> None:
    repository = _clone(tmp_path)
    receipt = _receipt(repository)
    receipt_path = tmp_path / "project-completion.json"
    archive_path = tmp_path / "source.tar.gz"
    _write_json(receipt_path, receipt)
    archive_path.write_bytes(build_completion_archive(repository, _head(repository)))
    message = _tag_message(repository, receipt_path, archive_path)
    subprocess.run(
        ["git", "tag", "--annotate", COMPLETION_TAG, "--message", message],
        cwd=repository,
        check=True,
    )
    verification = build_post_completion_verification(
        repository, COMPLETION_TAG, receipt_path, archive_path
    )
    assert verification["result"] == "PASS"
    assert verification["tag_type"] == "ANNOTATED"


def test_lightweight_tag_and_post_attestation_commit_are_rejected(tmp_path: Path) -> None:
    repository = _clone(tmp_path)
    receipt = _receipt(repository)
    receipt_path = tmp_path / "project-completion.json"
    archive_path = tmp_path / "source.tar.gz"
    _write_json(receipt_path, receipt)
    archive_path.write_bytes(build_completion_archive(repository, _head(repository)))
    subprocess.run(["git", "tag", COMPLETION_TAG], cwd=repository, check=True)
    with pytest.raises(ProjectCompletionError, match="not annotated"):
        build_post_completion_verification(repository, COMPLETION_TAG, receipt_path, archive_path)
    subprocess.run(["git", "tag", "--delete", COMPLETION_TAG], cwd=repository, check=True)
    subprocess.run(
        [
            "git",
            "tag",
            "--annotate",
            COMPLETION_TAG,
            "--message",
            _tag_message(repository, receipt_path, archive_path),
        ],
        cwd=repository,
        check=True,
    )
    marker = repository / "post-attestation.txt"
    marker.write_text("later change\n", encoding="utf-8")
    subprocess.run(["git", "add", "post-attestation.txt"], cwd=repository, check=True)
    subprocess.run(["git", "commit", "--quiet", "-m", "Later change"], cwd=repository, check=True)
    with pytest.raises(ProjectCompletionError, match="checkout is not tag target"):
        build_post_completion_verification(repository, COMPLETION_TAG, receipt_path, archive_path)


def test_policy_and_schema_files_are_digest_bound() -> None:
    assert len(sha256(ROOT / POLICY)) == 64
    assert len(sha256(ROOT / SCHEMA)) == 64
