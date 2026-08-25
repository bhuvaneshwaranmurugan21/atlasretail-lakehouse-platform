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


def _trust_policy() -> str:
    return json.dumps(
        {
            "Version": "2012-10-17",
            "Statement": [
                {
                    "Effect": "Allow",
                    "Principal": {"Service": "glue.amazonaws.com"},
                    "Action": "sts:AssumeRole",
                }
            ],
        },
        separators=(",", ":"),
    )


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


def _create_job(aws: AwsRunner, job_name: str, role_arn: str) -> None:
    command = json.dumps(
        {"Name": "glueetl", "ScriptLocation": SCRIPT_LOCATION, "PythonVersion": "3"},
        separators=(",", ":"),
    )

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
                "Project=atlasretail,Purpose=glue-service-probe",
            )
            return
        except AwsCallError as error:
            if _account_denied(error) or not _role_propagation(error):
                raise
            if attempt == ROLE_PROPAGATION_ATTEMPTS - 1:
                raise
            time.sleep(2)


def _absent(
    aws: AwsRunner,
    service: str,
    operation: str,
    argument_name: str,
    resource_name: str,
    missing_code: str,
) -> None:
    try:
        aws.run(service, operation, argument_name, resource_name)
    except AwsCallError as error:
        if missing_code in error.stderr:
            return
        raise
    raise ValueError(f"{service} resource {resource_name} still exists after deletion")


def probe(
    aws: AwsRunner,
    *,
    account: str,
    region: str,
    run_id: str,
    source_commit: str,
) -> dict[str, Any]:
    """Create and remove a definition-only Glue job, recording every outcome."""
    if account != EXPECTED_ACCOUNT or region != EXPECTED_REGION:
        raise ValueError("Probe account or region is outside its fixed boundary")
    if not re.fullmatch(r"\d{1,20}", run_id):
        raise ValueError("Probe run identifier must contain only digits")

    job_name = f"atlasretail-probe-{run_id}"
    role_name = f"{job_name}-glue"
    evidence: dict[str, Any] = {
        "account": account,
        "cleanup": {"glue_job": "NOT_CREATED", "iam_role": "NOT_CREATED"},
        "completed_at": None,
        "errors": [],
        "glue_job_name": job_name,
        "glue_job_runs": None,
        "iam_role_name": role_name,
        "region": region,
        "run_id": run_id,
        "source_commit": source_commit,
        "started_at": datetime.now(UTC).isoformat(),
        "status": "FAILED",
        "workload_started": False,
    }
    role_created = False
    job_created = False

    try:
        role = aws.run(
            "iam",
            "create-role",
            "--role-name",
            role_name,
            "--assume-role-policy-document",
            _trust_policy(),
            "--tags",
            "Key=Project,Value=atlasretail",
            "Key=Purpose,Value=glue-service-probe",
            f"Key=RunId,Value={run_id}",
        )
        role_created = True
        evidence["cleanup"]["iam_role"] = "PENDING"
        role_arn = role["Role"]["Arn"]
        if role_arn != f"arn:aws:iam::{account}:role/{role_name}":
            raise ValueError("Created IAM role ARN is outside the probe boundary")

        aws.run("iam", "get-role", "--role-name", role_name)
        _create_job(aws, job_name, role_arn)
        job_created = True
        evidence["cleanup"]["glue_job"] = "PENDING"

        job = aws.run("glue", "get-job", "--job-name", job_name)
        if job["Job"]["Name"] != job_name:
            raise ValueError("Glue returned a job outside the probe boundary")

        job_runs = aws.run("glue", "get-job-runs", "--job-name", job_name, "--max-results", "1")
        runs = job_runs.get("JobRuns")
        if not isinstance(runs, list):
            raise ValueError("Glue job-run response did not contain a run list")
        evidence["glue_job_runs"] = len(runs)
        if runs:
            raise ValueError("Probe Glue job unexpectedly contains an execution")

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
                aws.run("glue", "delete-job", "--job-name", job_name)
                _absent(
                    aws,
                    "glue",
                    "get-job",
                    "--job-name",
                    job_name,
                    "EntityNotFoundException",
                )
                evidence["cleanup"]["glue_job"] = "DELETED_AND_VERIFIED"
            except (AwsCallError, ValueError) as error:
                evidence["cleanup"]["glue_job"] = "FAILED"
                evidence["errors"].append(f"Glue job cleanup failed: {error}")
                evidence["status"] = "CLEANUP_INCOMPLETE"

        if role_created:
            try:
                aws.run("iam", "delete-role", "--role-name", role_name)
                _absent(aws, "iam", "get-role", "--role-name", role_name, "NoSuchEntity")
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
