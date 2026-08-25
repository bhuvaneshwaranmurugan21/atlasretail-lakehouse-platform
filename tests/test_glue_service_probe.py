"""Guard the definition-only AWS Glue capability probe and its cleanup contract."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any

ROOT = Path(__file__).parents[1]
SCRIPT = ROOT / "scripts" / "probe_glue_capability.py"
WORKFLOW = ROOT / ".github" / "workflows" / "aws-glue-service-probe.yml"
SPEC = importlib.util.spec_from_file_location("probe_glue_capability", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class FakeAws:
    """Model the precise IAM and Glue operations allowed to the probe."""

    def __init__(self, *, deny_create: bool = False, fail_delete: bool = False) -> None:
        self.deny_create = deny_create
        self.fail_delete = fail_delete
        self.role_exists = False
        self.job_exists = False
        self.calls: list[tuple[str, str]] = []

    def run(self, service: str, operation: str, *arguments: str) -> dict[str, Any]:
        self.calls.append((service, operation))
        if (service, operation) == ("iam", "create-role"):
            self.role_exists = True
            return {"Role": {"Arn": "arn:aws:iam::857229544428:role/atlasretail-probe-123-glue"}}
        if (service, operation) == ("iam", "get-role"):
            if not self.role_exists:
                raise MODULE.AwsCallError(service, operation, "NoSuchEntity: role does not exist")
            return {"Role": {"RoleName": "atlasretail-probe-123-glue"}}
        if (service, operation) == ("iam", "delete-role"):
            self.role_exists = False
            return {}
        if (service, operation) == ("glue", "create-job"):
            if self.deny_create:
                raise MODULE.AwsCallError(
                    service,
                    operation,
                    "AccessDeniedException: Account 857229544428 is denied access",
                )
            self.job_exists = True
            return {"Name": "atlasretail-probe-123"}
        if (service, operation) == ("glue", "get-job"):
            if not self.job_exists:
                raise MODULE.AwsCallError(service, operation, "EntityNotFoundException: absent")
            return {"Job": {"Name": "atlasretail-probe-123"}}
        if (service, operation) == ("glue", "get-job-runs"):
            return {"JobRuns": []}
        if (service, operation) == ("glue", "delete-job"):
            if self.fail_delete:
                raise MODULE.AwsCallError(service, operation, "AccessDeniedException: denied")
            self.job_exists = False
            return {"JobName": "atlasretail-probe-123"}
        raise AssertionError(f"Unexpected AWS operation: {service} {operation} {arguments}")


def run_probe(aws: FakeAws) -> dict[str, Any]:
    return MODULE.probe(
        aws,
        account="857229544428",
        region="ap-southeast-2",
        run_id="123",
        source_commit="abc123",
    )


def test_successful_probe_verifies_definition_and_deletes_both_resources() -> None:
    aws = FakeAws()

    evidence = run_probe(aws)

    assert evidence["status"] == "GLUE_CREATE_JOB_VERIFIED"
    assert evidence["glue_job_runs"] == 0
    assert evidence["workload_started"] is False
    assert evidence["cleanup"] == {
        "glue_job": "DELETED_AND_VERIFIED",
        "iam_role": "DELETED_AND_VERIFIED",
    }
    assert ("glue", "start-job-run") not in aws.calls
    assert not aws.job_exists
    assert not aws.role_exists


def test_account_denial_still_deletes_the_temporary_iam_role() -> None:
    aws = FakeAws(deny_create=True)

    evidence = run_probe(aws)

    assert evidence["status"] == "ACCOUNT_DENIED"
    assert evidence["cleanup"] == {
        "glue_job": "NOT_CREATED",
        "iam_role": "DELETED_AND_VERIFIED",
    }
    assert ("glue", "start-job-run") not in aws.calls
    assert not aws.role_exists


def test_cleanup_failure_overrides_an_otherwise_successful_probe() -> None:
    aws = FakeAws(fail_delete=True)

    evidence = run_probe(aws)

    assert evidence["status"] == "CLEANUP_INCOMPLETE"
    assert evidence["cleanup"]["glue_job"] == "FAILED"
    assert evidence["cleanup"]["iam_role"] == "DELETED_AND_VERIFIED"
    assert "Glue job cleanup failed" in evidence["errors"][0]


def test_probe_rejects_account_region_and_resource_name_boundary_violations() -> None:
    for account, region, run_id in (
        ("000000000000", "ap-southeast-2", "123"),
        ("857229544428", "us-east-1", "123"),
        ("857229544428", "ap-southeast-2", "123-unbounded"),
    ):
        aws = FakeAws()
        try:
            MODULE.probe(
                aws,
                account=account,
                region=region,
                run_id=run_id,
                source_commit="abc123",
            )
        except ValueError:
            assert not aws.calls
        else:
            raise AssertionError("Probe accepted an out-of-bounds input")


def test_workflow_is_manually_authorized_and_cannot_execute_a_workload() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")

    assert "workflow_dispatch:" in workflow
    assert "PROBE_GLUE_CREATE_DELETE" in workflow
    assert 'test "${GITHUB_ACTOR}" = "${GITHUB_REPOSITORY_OWNER}"' in workflow
    assert 'test "${GITHUB_REF}" = "refs/heads/main"' in workflow
    assert 'test "${AWS_REGION}" = "${{ steps.target.outputs.aws_region }}"' in workflow
    assert "group: portfolio-aws-account" in workflow
    assert "python scripts/load_aws_target.py" in workflow
    assert 'test "${account}" = "${AWS_ACCOUNT_ID}"' in workflow
    assert "python scripts/probe_glue_capability.py" in workflow
    assert "if: always() && steps.account_identity.outcome == 'success'" in workflow
    assert "actions/upload-artifact@" in workflow
    assert all(
        forbidden not in workflow
        for forbidden in ("start-job-run", "terraform", "cloudformation", "aws s3 cp")
    )
