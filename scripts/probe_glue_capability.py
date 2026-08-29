"""Prove Glue job-definition access without executing a Glue workload."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

TARGET = json.loads(
    (Path(__file__).resolve().parents[1] / ".github" / "atlas-target.json").read_text(
        encoding="utf-8"
    )
)
EXPECTED_ACCOUNT = TARGET["aws_account_id"]
EXPECTED_REGION = TARGET["aws_region"]
SCRIPT_LOCATION = f"s3://{TARGET['terraform_state_bucket']}/glue-probe/never-run.py"
ROLE_PROPAGATION_ATTEMPTS = 5
ABSENCE_ATTEMPTS = 6
RETRY_SECONDS = 2


class AwsCallError(RuntimeError):
    """Capture an AWS CLI service failure without exposing credentials."""

    def __init__(self, service: str, operation: str, stderr: str) -> None:
        self.service = service
        self.operation = operation
        self.stderr = stderr.strip()
        super().__init__(f"{service} {operation}: {self.stderr}")


class AwsRunner(Protocol):
    """Execute one bounded AWS API operation."""

    def run(self, service: str, operation: str, *arguments: str) -> dict[str, Any]: ...


class AwsCli:
    """Run AWS CLI operations using the workflow's short-lived credentials."""

    def __init__(self, region: str) -> None:
        self.region = region

    def run(self, service: str, operation: str, *arguments: str) -> dict[str, Any]:
        command = [
            "aws",
            service,
            operation,
            *arguments,
            "--region",
            self.region,
            "--output",
            "json",
            "--no-cli-pager",
        ]
        try:
            result = subprocess.run(command, capture_output=True, check=False, text=True)
        except OSError as error:
            raise AwsCallError(service, operation, str(error)) from error

        if result.returncode:
            raise AwsCallError(service, operation, result.stderr)
        if not result.stdout.strip():
            return {}

        payload = json.loads(result.stdout)
        if not isinstance(payload, dict):
            raise ValueError(f"{service} {operation} returned a non-object response")
        return payload


def validate_boundary(account: str, region: str, run_id: str, source_commit: str) -> None:
    if account != EXPECTED_ACCOUNT or region != EXPECTED_REGION:
        raise ValueError("probe account or region is outside its fixed boundary")
    if re.fullmatch(r"[1-9][0-9]{0,19}", run_id) is None:
        raise ValueError("probe run identifier must be a positive integer")
    if re.fullmatch(r"[0-9a-f]{40}", source_commit) is None:
        raise ValueError("source commit must contain exactly 40 lowercase hexadecimal characters")


def resource_names(account: str, region: str, run_id: str) -> dict[str, str]:
    job_name = f"atlasretail-probe-{run_id}"
    role_name = f"{job_name}-glue"
    return {
        "job_name": job_name,
        "job_arn": f"arn:aws:glue:{region}:{account}:job/{job_name}",
        "role_name": role_name,
        "role_arn": f"arn:aws:iam::{account}:role/{role_name}",
    }


def expected_tags(run_id: str) -> dict[str, str]:
    return {"Project": "atlasretail", "Purpose": "glue-service-probe", "RunId": run_id}


def _trust_policy_document() -> dict[str, Any]:
    return {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Principal": {"Service": "glue.amazonaws.com"},
                "Action": "sts:AssumeRole",
            }
        ],
    }


def _trust_policy() -> str:
    return json.dumps(_trust_policy_document(), separators=(",", ":"))


def _account_denied(error: AwsCallError) -> bool:
    return bool(re.search(r"Account\s+\d+\s+is denied access", error.stderr, re.IGNORECASE))


def _role_propagation(error: AwsCallError) -> bool:
    return bool(
        re.search(
            r"cannot be assumed|not authorized to assume|role.*not found|role does not exist",
            error.stderr,
            re.IGNORECASE,
        )
    )


def _request_id(message: str) -> str | None:
    match = re.search(r"(?:request[ -]?id)\s*[:=]\s*([\w-]+)", message, re.IGNORECASE)
    return match.group(1) if match else None


def _tags(payload: Any) -> dict[str, str]:
    if not isinstance(payload, list):
        raise ValueError("AWS tag response must contain a list")
    result: dict[str, str] = {}
    for item in payload:
        if not isinstance(item, dict) or set(item) != {"Key", "Value"}:
            raise ValueError("AWS tag response contains an invalid item")
        key = item["Key"]
        value = item["Value"]
        if not isinstance(key, str) or not isinstance(value, str) or key in result:
            raise ValueError("AWS tag response contains an invalid or duplicate key")
        result[key] = value
    return result


def _is_missing(error: AwsCallError, missing_code: str) -> bool:
    return missing_code in error.stderr


def require_absent(
    aws: AwsRunner,
    service: str,
    operation: str,
    argument_name: str,
    resource_name: str,
    missing_code: str,
) -> str:
    """Fail closed if the run-derived resource already exists."""
    try:
        aws.run(service, operation, argument_name, resource_name)
    except AwsCallError as error:
        if _is_missing(error, missing_code):
            return missing_code
        raise
    raise ValueError(f"{service} resource {resource_name} exists before probe creation")


def wait_absent(
    aws: AwsRunner,
    service: str,
    operation: str,
    argument_name: str,
    resource_name: str,
    missing_code: str,
    *,
    attempts: int = ABSENCE_ATTEMPTS,
    delay_seconds: int = RETRY_SECONDS,
) -> str:
    """Require an exact not-found response after bounded propagation retries."""
    for attempt in range(attempts):
        try:
            aws.run(service, operation, argument_name, resource_name)
        except AwsCallError as error:
            if _is_missing(error, missing_code):
                return missing_code
            raise
        if attempt < attempts - 1:
            time.sleep(delay_seconds)
    raise ValueError(f"{service} resource {resource_name} still exists after deletion")


def _create_job(aws: AwsRunner, job_name: str, role_arn: str, run_id: str) -> None:
    command = json.dumps(
        {"Name": "glueetl", "ScriptLocation": SCRIPT_LOCATION, "PythonVersion": "3"},
        separators=(",", ":"),
    )
    tags = f"Project=atlasretail,Purpose=glue-service-probe,RunId={run_id}"
    for attempt in range(ROLE_PROPAGATION_ATTEMPTS):
        try:
            aws.run(
                "glue",
                "create-job",
                "--name",
                job_name,
                "--role",
                role_arn,
                "--command",
                command,
                "--glue-version",
                "5.0",
                "--worker-type",
                "G.1X",
                "--number-of-workers",
                "2",
                "--timeout",
                "1",
                "--max-retries",
                "0",
                "--tags",
                tags,
            )
            return
        except AwsCallError as error:
            if _account_denied(error) or not _role_propagation(error):
                raise
            if attempt == ROLE_PROPAGATION_ATTEMPTS - 1:
                raise
            time.sleep(RETRY_SECONDS)


def verify_role(aws: AwsRunner, role_name: str, role_arn: str, run_id: str) -> dict[str, bool]:
    role_response = aws.run("iam", "get-role", "--role-name", role_name)
    role = role_response.get("Role")
    if not isinstance(role, dict):
        raise ValueError("IAM get-role response is missing Role")
    if role.get("RoleName") != role_name or role.get("Arn") != role_arn:
        raise ValueError("IAM returned a role outside the probe boundary")
    if role.get("AssumeRolePolicyDocument") != _trust_policy_document():
        raise ValueError("probe role trust policy differs from the Glue-only contract")
    tag_response = aws.run("iam", "list-role-tags", "--role-name", role_name)
    if _tags(tag_response.get("Tags")) != expected_tags(run_id):
        raise ValueError("probe role ownership tags differ from the exact contract")
    inline = aws.run("iam", "list-role-policies", "--role-name", role_name)
    attached = aws.run("iam", "list-attached-role-policies", "--role-name", role_name)
    if inline.get("PolicyNames") != [] or attached.get("AttachedPolicies") != []:
        raise ValueError("probe role is not inert")
    return {"exact_identity": True, "glue_only_trust": True, "no_permissions": True}


def verify_job(
    aws: AwsRunner, job_name: str, job_arn: str, role_arn: str, run_id: str
) -> dict[str, bool]:
    response = aws.run("glue", "get-job", "--job-name", job_name)
    job = response.get("Job")
    if not isinstance(job, dict):
        raise ValueError("Glue get-job response is missing Job")
    expected = {
        "Name": job_name,
        "Role": role_arn,
        "Command": {
            "Name": "glueetl",
            "ScriptLocation": SCRIPT_LOCATION,
            "PythonVersion": "3",
        },
        "GlueVersion": "5.0",
        "WorkerType": "G.1X",
        "NumberOfWorkers": 2,
        "Timeout": 1,
        "MaxRetries": 0,
    }
    for key, value in expected.items():
        if job.get(key) != value:
            raise ValueError(f"Glue job field {key} differs from the definition-only contract")
    tag_response = aws.run("glue", "get-tags", "--resource-arn", job_arn)
    tags = tag_response.get("Tags")
    if not isinstance(tags, dict) or tags != expected_tags(run_id):
        raise ValueError("probe job ownership tags differ from the exact contract")
    return {"exact_configuration": True, "exact_ownership": True}


def probe(
    aws: AwsRunner,
    *,
    account: str,
    region: str,
    run_id: str,
    source_commit: str,
) -> dict[str, Any]:
    """Create, inspect and remove one inert Glue job definition."""
    validate_boundary(account, region, run_id, source_commit)
    names = resource_names(account, region, run_id)
    evidence: dict[str, Any] = {
        "account": account,
        "cleanup": {"glue_job": "NOT_CREATED", "iam_role": "NOT_CREATED"},
        "completed_at": None,
        "errors": [],
        "glue_job_name": names["job_name"],
        "glue_job_runs": None,
        "iam_role_name": names["role_name"],
        "job_definition": None,
        "region": region,
        "role_inertness": None,
        "run_id": run_id,
        "source_commit": source_commit,
        "started_at": datetime.now(UTC).isoformat(),
        "status": "FAILED",
        "workload_started": False,
    }
    role_created = False
    job_created = False
    try:
        require_absent(
            aws, "glue", "get-job", "--job-name", names["job_name"], "EntityNotFoundException"
        )
        require_absent(aws, "iam", "get-role", "--role-name", names["role_name"], "NoSuchEntity")
        role = aws.run(
            "iam",
            "create-role",
            "--role-name",
            names["role_name"],
            "--assume-role-policy-document",
            _trust_policy(),
            "--tags",
            "Key=Project,Value=atlasretail",
            "Key=Purpose,Value=glue-service-probe",
            f"Key=RunId,Value={run_id}",
        )
        role_created = True
        evidence["cleanup"]["iam_role"] = "PENDING"
        if role.get("Role", {}).get("Arn") != names["role_arn"]:
            raise ValueError("created IAM role ARN is outside the probe boundary")
        evidence["role_inertness"] = verify_role(aws, names["role_name"], names["role_arn"], run_id)
        _create_job(aws, names["job_name"], names["role_arn"], run_id)
        job_created = True
        evidence["cleanup"]["glue_job"] = "PENDING"
        evidence["job_definition"] = verify_job(
            aws, names["job_name"], names["job_arn"], names["role_arn"], run_id
        )
        job_runs = aws.run(
            "glue", "get-job-runs", "--job-name", names["job_name"], "--max-results", "1"
        )
        runs = job_runs.get("JobRuns")
        if not isinstance(runs, list):
            raise ValueError("Glue job-run response did not contain a run list")
        evidence["glue_job_runs"] = len(runs)
        if runs:
            raise ValueError("probe Glue job unexpectedly contains an execution")
        evidence["status"] = "GLUE_CREATE_JOB_VERIFIED"
    except (AwsCallError, KeyError, TypeError, ValueError) as error:
        evidence["errors"].append(str(error))
        if isinstance(error, AwsCallError):
            evidence["request_id"] = _request_id(error.stderr)
            if _account_denied(error):
                evidence["status"] = "ACCOUNT_DENIED"
            elif _role_propagation(error):
                evidence["status"] = "IAM_ROLE_PROPAGATION_FAILED"
    finally:
        if job_created:
            try:
                aws.run("glue", "delete-job", "--job-name", names["job_name"])
                wait_absent(
                    aws,
                    "glue",
                    "get-job",
                    "--job-name",
                    names["job_name"],
                    "EntityNotFoundException",
                )
                evidence["cleanup"]["glue_job"] = "DELETED_AND_VERIFIED"
            except (AwsCallError, ValueError) as error:
                evidence["cleanup"]["glue_job"] = "FAILED"
                evidence["errors"].append(f"Glue job cleanup failed: {error}")
                evidence["status"] = "CLEANUP_INCOMPLETE"
        if role_created:
            try:
                aws.run("iam", "delete-role", "--role-name", names["role_name"])
                wait_absent(
                    aws,
                    "iam",
                    "get-role",
                    "--role-name",
                    names["role_name"],
                    "NoSuchEntity",
                )
                evidence["cleanup"]["iam_role"] = "DELETED_AND_VERIFIED"
            except (AwsCallError, ValueError) as error:
                evidence["cleanup"]["iam_role"] = "FAILED"
                evidence["errors"].append(f"IAM role cleanup failed: {error}")
                evidence["status"] = "CLEANUP_INCOMPLETE"
        evidence["completed_at"] = datetime.now(UTC).isoformat()
    return evidence


def main(arguments: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--account", required=True)
    parser.add_argument("--region", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(arguments)
    try:
        evidence = probe(
            AwsCli(args.region),
            account=args.account,
            region=args.region,
            run_id=args.run_id,
            source_commit=args.source_commit,
        )
    except ValueError as error:
        print(f"Glue probe rejected before resource creation: {error}", file=sys.stderr)
        return 2
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(evidence, sort_keys=True))
    return 0 if evidence["status"] == "GLUE_CREATE_JOB_VERIFIED" else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
