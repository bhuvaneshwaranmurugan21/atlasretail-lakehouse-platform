"""Guard the least-privilege Glue definition probe and independent cleanup contract."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import build_glue_probe_session_policy as POLICY  # noqa: E402
import cleanup_glue_probe as CLEANUP  # noqa: E402
import finalize_glue_probe_evidence as FINALIZE  # noqa: E402
import probe_glue_capability as PROBE  # noqa: E402

WORKFLOW = ROOT / ".github" / "workflows" / "aws-glue-service-probe.yml"
ACCOUNT = "857229544428"
REGION = "ap-southeast-2"
RUN_ID = "123"
SOURCE = "a" * 40
ROLE_NAME = "atlasretail-probe-123-glue"
ROLE_ARN = f"arn:aws:iam::{ACCOUNT}:role/{ROLE_NAME}"
JOB_NAME = "atlasretail-probe-123"
JOB_ARN = f"arn:aws:glue:{REGION}:{ACCOUNT}:job/{JOB_NAME}"
TAGS = {"Project": "atlasretail", "Purpose": "glue-service-probe", "RunId": RUN_ID}


class FakeAws:
    """Model only the exact IAM and Glue operations available to Phase 4."""

    def __init__(
        self,
        *,
        deny_create: bool = False,
        fail_delete: bool = False,
        job_runs: list[dict[str, Any]] | None = None,
        tags: dict[str, str] | None = None,
    ) -> None:
        self.deny_create = deny_create
        self.fail_delete = fail_delete
        self.job_runs = [] if job_runs is None else job_runs
        self.tags = TAGS if tags is None else tags
        self.role_exists = False
        self.job_exists = False
        self.inline_policies: list[str] = []
        self.attached_policies: list[dict[str, str]] = []
        self.calls: list[tuple[str, str]] = []

    def run(self, service: str, operation: str, *arguments: str) -> dict[str, Any]:
        self.calls.append((service, operation))
        if (service, operation) == ("iam", "create-role"):
            self.role_exists = True
            return {"Role": {"Arn": ROLE_ARN}}
        if (service, operation) == ("iam", "get-role"):
            if not self.role_exists:
                raise PROBE.AwsCallError(service, operation, "NoSuchEntity: role does not exist")
            return {
                "Role": {
                    "Arn": ROLE_ARN,
                    "AssumeRolePolicyDocument": PROBE._trust_policy_document(),
                    "RoleName": ROLE_NAME,
                }
            }
        if (service, operation) == ("iam", "list-role-tags"):
            return {"Tags": [{"Key": key, "Value": value} for key, value in self.tags.items()]}
        if (service, operation) == ("iam", "list-role-policies"):
            return {"PolicyNames": self.inline_policies}
        if (service, operation) == ("iam", "list-attached-role-policies"):
            return {"AttachedPolicies": self.attached_policies}
        if (service, operation) == ("iam", "delete-role"):
            if self.inline_policies or self.attached_policies:
                raise PROBE.AwsCallError(service, operation, "DeleteConflict: role has policies")
            self.role_exists = False
            return {}
        if (service, operation) == ("glue", "create-job"):
            if self.deny_create:
                raise PROBE.AwsCallError(
                    service,
                    operation,
                    "AccessDeniedException: Account 857229544428 is denied access",
                )
            self.job_exists = True
            return {"Name": JOB_NAME}
        if (service, operation) == ("glue", "get-job"):
            if not self.job_exists:
                raise PROBE.AwsCallError(service, operation, "EntityNotFoundException: absent")
            return {
                "Job": {
                    "Command": {
                        "Name": "glueetl",
                        "PythonVersion": "3",
                        "ScriptLocation": PROBE.SCRIPT_LOCATION,
                    },
                    "GlueVersion": "5.0",
                    "MaxRetries": 0,
                    "Name": JOB_NAME,
                    "NumberOfWorkers": 2,
                    "Role": ROLE_ARN,
                    "Timeout": 1,
                    "WorkerType": "G.1X",
                }
            }
        if (service, operation) == ("glue", "get-tags"):
            return {"Tags": self.tags}
        if (service, operation) == ("glue", "get-job-runs"):
            return {"JobRuns": self.job_runs}
        if (service, operation) == ("glue", "delete-job"):
            if self.fail_delete:
                raise PROBE.AwsCallError(service, operation, "AccessDeniedException: denied")
            self.job_exists = False
            return {"JobName": JOB_NAME}
        raise AssertionError(f"Unexpected AWS operation: {service} {operation} {arguments}")


def run_probe(aws: FakeAws) -> dict[str, Any]:
    return PROBE.probe(aws, account=ACCOUNT, region=REGION, run_id=RUN_ID, source_commit=SOURCE)


def test_session_policies_are_exact_bounded_and_deny_workloads() -> None:
    probe = POLICY.build_policy(RUN_ID, "probe")
    cleanup = POLICY.build_policy(RUN_ID, "cleanup")
    probe_text = POLICY.render_policy(RUN_ID, "probe")
    cleanup_text = POLICY.render_policy(RUN_ID, "cleanup")

    assert len(probe_text) <= 2048
    assert len(cleanup_text) <= 2048
    assert ROLE_ARN in probe_text and JOB_ARN in probe_text
    assert ROLE_ARN in cleanup_text and JOB_ARN in cleanup_text
    denied = next(item for item in probe["Statement"] if item["Sid"] == "DenyWorkloadExecution")
    assert set(denied["Action"]) == set(POLICY.WORKLOAD_ACTIONS)
    assert not any(item.get("Action") == "iam:PassRole" for item in cleanup["Statement"])
    assert "glue:CreateJob" not in cleanup_text

    parent = json.loads(
        (ROOT / "infra" / "iam" / "atlasretail-github-role-policy.json").read_text(encoding="utf-8")
    )
    parent_actions = {
        action
        for statement in parent["Statement"]
        for action in (
            [statement["Action"]] if isinstance(statement["Action"], str) else statement["Action"]
        )
    }
    for document in (probe, cleanup):
        allowed_actions = {
            action
            for statement in document["Statement"]
            if statement["Effect"] == "Allow"
            for action in (
                [statement["Action"]]
                if isinstance(statement["Action"], str)
                else statement["Action"]
            )
        }
        assert allowed_actions <= parent_actions


@pytest.mark.parametrize("run_id", ("0", "-1", "abc", "1" * 21))
def test_session_policy_rejects_invalid_run_ids(run_id: str) -> None:
    with pytest.raises(ValueError):
        POLICY.build_policy(run_id, "probe")


def test_successful_probe_verifies_definition_role_zero_runs_and_cleanup() -> None:
    aws = FakeAws()
    evidence = run_probe(aws)

    assert evidence["status"] == "GLUE_CREATE_JOB_VERIFIED"
    assert evidence["glue_job_runs"] == 0
    assert evidence["workload_started"] is False
    assert evidence["role_inertness"]["no_permissions"] is True
    assert evidence["job_definition"]["exact_configuration"] is True
    assert evidence["cleanup"] == {
        "glue_job": "DELETED_AND_VERIFIED",
        "iam_role": "DELETED_AND_VERIFIED",
    }
    assert ("glue", "start-job-run") not in aws.calls
    assert not aws.job_exists and not aws.role_exists


def test_account_denial_still_deletes_the_temporary_inert_role() -> None:
    aws = FakeAws(deny_create=True)
    evidence = run_probe(aws)

    assert evidence["status"] == "ACCOUNT_DENIED"
    assert evidence["cleanup"] == {
        "glue_job": "NOT_CREATED",
        "iam_role": "DELETED_AND_VERIFIED",
    }
    assert not aws.role_exists


def test_cleanup_failure_overrides_an_otherwise_successful_probe() -> None:
    aws = FakeAws(fail_delete=True)
    evidence = run_probe(aws)

    assert evidence["status"] == "CLEANUP_INCOMPLETE"
    assert evidence["cleanup"]["glue_job"] == "FAILED"
    assert evidence["cleanup"]["iam_role"] == "DELETED_AND_VERIFIED"
    assert any("Glue job cleanup failed" in error for error in evidence["errors"])


def test_nonzero_job_runs_fail_the_probe_but_still_clean_resources() -> None:
    aws = FakeAws(job_runs=[{"Id": "unexpected"}])
    evidence = run_probe(aws)

    assert evidence["status"] == "FAILED"
    assert evidence["glue_job_runs"] == 1
    assert evidence["cleanup"] == {
        "glue_job": "DELETED_AND_VERIFIED",
        "iam_role": "DELETED_AND_VERIFIED",
    }
    assert not aws.job_exists and not aws.role_exists


def test_probe_rejects_a_preexisting_run_derived_resource_without_deleting_it() -> None:
    aws = FakeAws()
    aws.role_exists = True
    evidence = run_probe(aws)

    assert evidence["status"] == "FAILED"
    assert aws.role_exists
    assert ("iam", "delete-role") not in aws.calls


def test_probe_rejects_bounds_before_any_aws_call() -> None:
    for account, region, run_id, source in (
        ("000000000000", REGION, RUN_ID, SOURCE),
        (ACCOUNT, "us-east-1", RUN_ID, SOURCE),
        (ACCOUNT, REGION, "123-unbounded", SOURCE),
        (ACCOUNT, REGION, RUN_ID, "abc123"),
    ):
        aws = FakeAws()
        with pytest.raises(ValueError):
            PROBE.probe(aws, account=account, region=region, run_id=run_id, source_commit=source)
        assert not aws.calls


def test_independent_cleanup_is_idempotent_for_absent_resources() -> None:
    evidence = CLEANUP.cleanup(
        FakeAws(), account=ACCOUNT, region=REGION, run_id=RUN_ID, source_commit=SOURCE
    )
    assert evidence["result"] == "PASS"
    assert evidence["glue_job_lookup_result"] == "EntityNotFoundException"
    assert evidence["iam_role_lookup_result"] == "NoSuchEntity"


def test_independent_cleanup_deletes_only_exactly_owned_inert_resources() -> None:
    aws = FakeAws()
    aws.job_exists = True
    aws.role_exists = True
    evidence = CLEANUP.cleanup(
        aws, account=ACCOUNT, region=REGION, run_id=RUN_ID, source_commit=SOURCE
    )
    assert evidence["result"] == "PASS"
    assert not aws.job_exists and not aws.role_exists


def test_independent_cleanup_refuses_ownership_mismatch() -> None:
    aws = FakeAws(tags={**TAGS, "RunId": "999"})
    aws.job_exists = True
    aws.role_exists = True
    evidence = CLEANUP.cleanup(
        aws, account=ACCOUNT, region=REGION, run_id=RUN_ID, source_commit=SOURCE
    )
    assert evidence["result"] == "FAIL"
    assert aws.job_exists and aws.role_exists
    assert any("mismatched ownership" in error for error in evidence["errors"])


def test_independent_cleanup_refuses_a_role_with_permissions() -> None:
    aws = FakeAws()
    aws.role_exists = True
    aws.attached_policies = [{"PolicyArn": "arn:aws:iam::aws:policy/ReadOnlyAccess"}]
    evidence = CLEANUP.cleanup(
        aws, account=ACCOUNT, region=REGION, run_id=RUN_ID, source_commit=SOURCE
    )

    assert evidence["result"] == "FAIL"
    assert aws.role_exists
    assert any("unexpected permissions" in error for error in evidence["errors"])


def test_absence_verifier_retries_only_resource_visibility() -> None:
    class EventuallyAbsent:
        calls = 0

        def run(self, service: str, operation: str, *arguments: str) -> dict[str, Any]:
            self.calls += 1
            if self.calls == 3:
                raise PROBE.AwsCallError(service, operation, "EntityNotFoundException: absent")
            return {"Job": {"Name": JOB_NAME}}

    aws = EventuallyAbsent()
    result = PROBE.wait_absent(
        aws,
        "glue",
        "get-job",
        "--job-name",
        JOB_NAME,
        "EntityNotFoundException",
        attempts=3,
        delay_seconds=0,
    )
    assert result == "EntityNotFoundException"
    assert aws.calls == 3


def write_json(path: Path, value: dict[str, Any]) -> None:
    path.write_text(json.dumps(value, sort_keys=True) + "\n", encoding="utf-8")


def valid_evidence(path: Path) -> None:
    source = FINALIZE.expected_source(
        SOURCE, RUN_ID, "bhuvaneshwaranmurugan21/atlasretail-lakehouse-platform", "refs/heads/main"
    )
    write_json(path / "source-identity.json", source)
    write_json(path / "cleanup-source-identity.json", source)
    write_json(
        path / "caller-identity.json",
        {
            "Account": ACCOUNT,
            "Arn": (
                f"arn:aws:sts::{ACCOUNT}:assumed-role/AtlasRetailGitHubOidcRole/"
                f"atlasretail-glue-probe-{RUN_ID}"
            ),
        },
    )
    write_json(
        path / "cleanup-caller-identity.json",
        {
            "Account": ACCOUNT,
            "Arn": (
                f"arn:aws:sts::{ACCOUNT}:assumed-role/AtlasRetailGitHubOidcRole/"
                f"atlasretail-glue-cleanup-{RUN_ID}"
            ),
        },
    )
    write_json(path / "probe-session-policy.json", POLICY.build_policy(RUN_ID, "probe"))
    write_json(path / "cleanup-session-policy.json", POLICY.build_policy(RUN_ID, "cleanup"))
    write_json(
        path / "glue-service-probe.json",
        {
            "account": ACCOUNT,
            "cleanup": {
                "glue_job": "DELETED_AND_VERIFIED",
                "iam_role": "DELETED_AND_VERIFIED",
            },
            "errors": [],
            "glue_job_runs": 0,
            "job_definition": {"exact_configuration": True, "exact_ownership": True},
            "region": REGION,
            "role_inertness": {
                "exact_identity": True,
                "glue_only_trust": True,
                "no_permissions": True,
            },
            "run_id": RUN_ID,
            "source_commit": SOURCE,
            "status": "GLUE_CREATE_JOB_VERIFIED",
            "workload_started": False,
        },
    )
    write_json(
        path / "cleanup-verification.json",
        {
            "account": ACCOUNT,
            "errors": [],
            "glue_job_lookup_result": "EntityNotFoundException",
            "glue_job_runs": None,
            "iam_role_lookup_result": "NoSuchEntity",
            "region": REGION,
            "result": "PASS",
            "run_id": RUN_ID,
            "source_commit": SOURCE,
        },
    )


def finalize(path: Path) -> dict[str, Any]:
    return FINALIZE.finalize(
        path,
        account=ACCOUNT,
        region=REGION,
        run_id=RUN_ID,
        source_commit=SOURCE,
        repository="bhuvaneshwaranmurugan21/atlasretail-lakehouse-platform",
        ref="refs/heads/main",
        probe_job_result="success",
        cleanup_job_result="success",
    )


def test_finalizer_accepts_only_the_complete_consistent_contract(tmp_path: Path) -> None:
    valid_evidence(tmp_path)
    summary = finalize(tmp_path)

    assert summary["result"] == "PASS"
    assert summary["claim"] == "AWS_GLUE_DEFINITION_CAPABILITY_VERIFIED"
    manifest = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["result"] == "PASS"
    assert set(manifest["files"]) == FINALIZE.RAW_FILES | {"phase-4-summary.json"}


def test_finalizer_rejects_a_nonzero_job_run(tmp_path: Path) -> None:
    valid_evidence(tmp_path)
    probe_path = tmp_path / "glue-service-probe.json"
    probe = json.loads(probe_path.read_text(encoding="utf-8"))
    probe["glue_job_runs"] = 1
    write_json(probe_path, probe)

    summary = finalize(tmp_path)
    assert summary["result"] == "FAIL"
    assert summary["claim"] == "UNCLAIMED"
    assert summary["workload_started"] == "UNCLAIMED"


def test_finalizer_rejects_a_missing_evidence_file(tmp_path: Path) -> None:
    valid_evidence(tmp_path)
    (tmp_path / "cleanup-verification.json").unlink()

    summary = finalize(tmp_path)
    assert summary["result"] == "FAIL"
    assert any("file set" in error for error in summary["errors"])


def test_workflow_has_separate_restricted_cleanup_and_fail_closed_finalization() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")

    assert "workflow_dispatch:" in workflow
    assert "PROBE_GLUE_CREATE_DELETE" in workflow
    assert 'test "${GITHUB_ACTOR}" = "${GITHUB_REPOSITORY_OWNER}"' in workflow
    assert workflow.count('test "${GITHUB_REF}" = "refs/heads/main"') == 2
    assert "group: portfolio-aws-account" in workflow
    assert workflow.count("python scripts/load_aws_target.py") == 2
    assert workflow.count("inline-session-policy:") == 2
    assert workflow.count("role-duration-seconds: 900") == 2
    assert workflow.count("allowed-account-ids:") == 2
    assert "needs: probe" in workflow
    assert "needs: [probe, cleanup]" in workflow
    assert "python scripts/cleanup_glue_probe.py" in workflow
    assert "python scripts/finalize_glue_probe_evidence.py" in workflow
    assert "retention-days: 30" in workflow
    assert all(
        forbidden not in workflow
        for forbidden in ("start-job-run", "terraform", "cloudformation", "aws s3 cp")
    )
