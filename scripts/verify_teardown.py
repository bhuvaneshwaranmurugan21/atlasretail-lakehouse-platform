"""Fail closed unless Terraform state and AWS inventories prove teardown."""

from __future__ import annotations

import json
import subprocess
import sys
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any

Runner = Callable[..., tuple[int, str]]
TARGET = json.loads(
    (Path(__file__).resolve().parents[1] / ".github" / "atlas-target.json").read_text(
        encoding="utf-8"
    )
)
EXPECTED_REGION = TARGET["aws_region"]


def command(*arguments: str) -> tuple[int, str]:
    """Run a command without raising so every cleanup check reaches the report."""
    completed = subprocess.run(arguments, check=False, capture_output=True, text=True)
    return completed.returncode, completed.stdout + completed.stderr


def output_value(outputs: dict[str, Any], name: str) -> str:
    """Read a required string from Terraform's output JSON."""
    value = outputs.get(name, {}).get("value")
    if not isinstance(value, str) or not value:
        raise ValueError(f"Terraform output {name!r} is missing or is not a string")
    return value


def output_or_default(outputs: dict[str, Any], name: str, default: str) -> str:
    """Use a deterministic Terraform name when a partial apply omitted an output."""
    value = outputs.get(name, {}).get("value")
    return value if isinstance(value, str) and value else default


def confirmed_absent(code: int, detail: str, markers: Iterable[str]) -> bool:
    """Accept only an explicit service-specific not-found response."""
    normalized = detail.lower()
    return code != 0 and any(marker.lower() in normalized for marker in markers)


def json_object(code: int, detail: str) -> dict[str, Any] | None:
    """Return a successful JSON object or None for any API/JSON failure."""
    if code != 0 or not detail.strip():
        return None
    try:
        parsed = json.loads(detail)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def terraform_resources(module: dict[str, Any]) -> list[str]:
    """Collect resource addresses recursively from Terraform's JSON state."""
    resources = [
        resource.get("address", "unknown")
        for resource in module.get("resources", [])
        if isinstance(resource, dict)
    ]
    for child in module.get("child_modules", []):
        if isinstance(child, dict):
            resources.extend(terraform_resources(child))
    return resources


def verify(
    outputs: dict[str, Any],
    terraform_directory: str,
    run_id: str,
    runner: Runner = command,
) -> dict[str, Any]:
    """Verify every resource class, Terraform state, and the RunId inventory."""
    checks: list[dict[str, Any]] = []
    prefix = f"atlasretail-{run_id}"

    def add(resource: str, deleted: bool, detail: str) -> None:
        checks.append({"resource": resource, "deleted": deleted, "detail": detail[-1000:]})

    for output_name in ("landing_bucket", "warehouse_bucket", "evidence_bucket"):
        try:
            name = output_value(outputs, output_name)
        except ValueError as error:
            add(output_name, False, str(error))
            continue
        code, detail = runner("aws", "s3api", "head-bucket", "--bucket", name)
        add(name, confirmed_absent(code, detail, ("404", "NoSuchBucket")), detail)

    named_checks = (
        (
            output_or_default(outputs, "control_table", f"{prefix}-control"),
            ("aws", "dynamodb", "describe-table", "--table-name"),
            ("ResourceNotFoundException",),
        ),
        (
            output_or_default(outputs, "glue_job_name", f"{prefix}-iceberg"),
            ("aws", "glue", "get-job", "--job-name"),
            ("EntityNotFoundException",),
        ),
        (
            output_or_default(
                outputs,
                "glue_database",
                f"{prefix}_retail".replace("-", "_"),
            ),
            ("aws", "glue", "get-database", "--name"),
            ("EntityNotFoundException",),
        ),
        (
            output_or_default(outputs, "athena_workgroup", f"{prefix}-verification"),
            ("aws", "athena", "get-work-group", "--work-group"),
            ("not found", "does not exist"),
        ),
        (
            output_or_default(outputs, "lambda_function_name", f"{prefix}-control"),
            ("aws", "lambda", "get-function", "--function-name"),
            ("ResourceNotFoundException",),
        ),
    )
    for name, command_prefix, markers in named_checks:
        code, detail = runner(*command_prefix, name)
        add(name, confirmed_absent(code, detail, markers), detail)

    try:
        state_machine_arn = output_value(outputs, "state_machine_arn")
    except ValueError:
        identity_code, identity_detail = runner(
            "aws", "sts", "get-caller-identity", "--output", "json"
        )
        identity = json_object(identity_code, identity_detail)
        account = identity.get("Account") if identity else None
        if not isinstance(account, str) or not account:
            add(
                "state_machine_arn",
                False,
                "Terraform output is missing and caller identity could not construct the ARN.",
            )
            state_machine_arn = ""
        else:
            state_machine_arn = (
                f"arn:aws:states:{EXPECTED_REGION}:{account}:stateMachine:{prefix}-pipeline"
            )
    if state_machine_arn:
        code, detail = runner(
            "aws",
            "stepfunctions",
            "describe-state-machine",
            "--state-machine-arn",
            state_machine_arn,
        )
        add(
            state_machine_arn,
            confirmed_absent(code, detail, ("StateMachineDoesNotExist",)),
            detail,
        )

    for output_name, suffix in (
        ("glue_role_name", "glue"),
        ("states_role_name", "states"),
        ("lambda_role_name", "lambda"),
    ):
        role_name = output_or_default(outputs, output_name, f"{prefix}-{suffix}")
        code, detail = runner("aws", "iam", "get-role", "--role-name", role_name)
        add(role_name, confirmed_absent(code, detail, ("NoSuchEntity",)), detail)

    for output_name, default_name in (
        ("glue_log_group_name", f"/aws-glue/jobs/{prefix}"),
        ("states_log_group_name", f"/aws/vendedlogs/states/{prefix}"),
        ("lambda_log_group_name", f"/aws/lambda/{prefix}-control"),
    ):
        log_group = output_or_default(outputs, output_name, default_name)
        code, detail = runner(
            "aws",
            "logs",
            "describe-log-groups",
            "--log-group-name-prefix",
            log_group,
            "--output",
            "json",
        )
        response = json_object(code, detail)
        exact_matches = []
        if response is not None:
            exact_matches = [
                group
                for group in response.get("logGroups", [])
                if isinstance(group, dict) and group.get("logGroupName") == log_group
            ]
        add(
            log_group,
            response is not None and not exact_matches,
            detail if response is None or exact_matches else "Exact log group is absent.",
        )

    alarm_name = output_or_default(outputs, "pipeline_alarm_name", f"{prefix}-pipeline-failed")
    alarm_code, alarm_detail = runner(
        "aws",
        "cloudwatch",
        "describe-alarms",
        "--alarm-names",
        alarm_name,
        "--output",
        "json",
    )
    alarm_response = json_object(alarm_code, alarm_detail)
    alarm_exists = False
    if alarm_response is not None:
        alarm_exists = any(
            alarm.get("AlarmName") == alarm_name
            for collection in ("MetricAlarms", "CompositeAlarms")
            for alarm in alarm_response.get(collection, [])
            if isinstance(alarm, dict)
        )
    add(
        alarm_name,
        alarm_response is not None and not alarm_exists,
        alarm_detail if alarm_response is None or alarm_exists else "Exact alarm is absent.",
    )

    kms_pending_deletion = False
    kms_key_arn = ""
    try:
        kms_key_arn = output_value(outputs, "kms_key_arn")
    except ValueError as error:
        add("kms_key_arn", False, str(error))
    if kms_key_arn:
        alias_name = output_or_default(outputs, "kms_alias_name", f"alias/{prefix}")
        alias_code, alias_detail = runner(
            "aws", "kms", "list-aliases", "--key-id", kms_key_arn, "--output", "json"
        )
        alias_response = json_object(alias_code, alias_detail)
        alias_exists = False
        if alias_response is not None:
            alias_exists = any(
                alias.get("AliasName") == alias_name
                for alias in alias_response.get("Aliases", [])
                if isinstance(alias, dict)
            )
        add(
            alias_name,
            alias_response is not None and not alias_exists,
            alias_detail if alias_response is None or alias_exists else "KMS alias is absent.",
        )

        key_code, key_detail = runner(
            "aws", "kms", "describe-key", "--key-id", kms_key_arn, "--output", "json"
        )
        key_response = json_object(key_code, key_detail)
        metadata = key_response.get("KeyMetadata", {}) if key_response else {}
        kms_pending_deletion = (
            isinstance(metadata, dict)
            and metadata.get("KeyState") == "PendingDeletion"
            and bool(metadata.get("DeletionDate"))
        )
        add(
            kms_key_arn,
            kms_pending_deletion,
            (
                "KMS key is PendingDeletion with a deletion date."
                if kms_pending_deletion
                else key_detail or "KMS key state could not be proven PendingDeletion."
            ),
        )

    state_code, state_json = runner("terraform", f"-chdir={terraform_directory}", "show", "-json")
    state = json_object(state_code, state_json)
    if state is None:
        state_empty = False
        state_detail = (
            f"Terraform state is unreadable: {state_json[-500:]}"
            if state_code != 0
            else "Terraform state output is empty or invalid JSON."
        )
    else:
        root_module = state.get("values", {}).get("root_module", {})
        remaining_state = terraform_resources(root_module) if isinstance(root_module, dict) else []
        state_empty = not remaining_state
        state_detail = (
            "Terraform state is readable and empty."
            if state_empty
            else json.dumps({"remaining_resources": remaining_state}, sort_keys=True)
        )
    add("terraform-state", state_empty, state_detail)

    tag_code, tag_detail = runner(
        "aws",
        "resourcegroupstaggingapi",
        "get-resources",
        "--tag-filters",
        f"Key=RunId,Values={run_id}",
        "--output",
        "json",
    )
    tag_response = json_object(tag_code, tag_detail)
    inventory_clean = False
    if tag_response is None:
        inventory_detail = f"RunId tag inventory is unreadable: {tag_detail[-500:]}"
    else:
        remaining = {
            mapping.get("ResourceARN")
            for mapping in tag_response.get("ResourceTagMappingList", [])
            if isinstance(mapping, dict) and mapping.get("ResourceARN")
        }
        allowed = {kms_key_arn} if kms_key_arn and kms_pending_deletion else set()
        unexpected = sorted(remaining - allowed)
        inventory_clean = not unexpected
        inventory_detail = json.dumps(
            {
                "allowed_pending_deletion_kms_keys": sorted(remaining & allowed),
                "unexpected_resources": unexpected,
            },
            sort_keys=True,
        )
    add(f"RunId={run_id} tag inventory", inventory_clean, inventory_detail)

    return {
        "result": "PASS" if all(check["deleted"] for check in checks) else "FAIL",
        "checks": checks,
        "kms_note": (
            "A RunId-tagged KMS key is allowed only when DescribeKey proves "
            "PendingDeletion and supplies a deletion date."
        ),
    }


def main(arguments: list[str]) -> int:
    """Write machine-readable teardown evidence and return its status."""
    if len(arguments) != 5:
        print(
            "usage: verify_teardown.py OUTPUTS_JSON TF_DIR RUN_ID EVIDENCE_JSON",
            file=sys.stderr,
        )
        return 2
    try:
        parsed_outputs = json.loads(Path(arguments[1]).read_text(encoding="utf-8"))
        outputs = parsed_outputs if isinstance(parsed_outputs, dict) else {}
    except (OSError, json.JSONDecodeError):
        outputs = {}
    result = verify(outputs, arguments[2], arguments[3])
    evidence_path = Path(arguments[4])
    evidence_path.parent.mkdir(parents=True, exist_ok=True)
    evidence_path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return 0 if result["result"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
