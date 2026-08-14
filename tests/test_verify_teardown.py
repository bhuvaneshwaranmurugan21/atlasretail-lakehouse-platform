"""Tests for fail-closed AWS teardown verification."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import ModuleType

SCRIPT = Path(__file__).parents[1] / "scripts" / "verify_teardown.py"
SPEC = importlib.util.spec_from_file_location("verify_teardown", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)

OUTPUTS = {
    "landing_bucket": {"value": "atlasretail-landing-test"},
    "warehouse_bucket": {"value": "atlasretail-warehouse-test"},
    "evidence_bucket": {"value": "atlasretail-evidence-test"},
    "control_table": {"value": "atlasretail-control-test"},
    "glue_job_name": {"value": "atlasretail-job-test"},
    "glue_database": {"value": "atlasretail_test_retail"},
    "athena_workgroup": {"value": "atlasretail-test-verification"},
    "lambda_function_name": {"value": "atlasretail-test-control"},
    "state_machine_arn": {"value": "arn:aws:states:ap-south-1:887720497919:stateMachine:test"},
    "glue_role_name": {"value": "atlasretail-test-glue"},
    "states_role_name": {"value": "atlasretail-test-states"},
    "lambda_role_name": {"value": "atlasretail-test-lambda"},
    "glue_log_group_name": {"value": "/aws-glue/jobs/atlasretail-test"},
    "states_log_group_name": {"value": "/aws/vendedlogs/states/atlasretail-test"},
    "lambda_log_group_name": {"value": "/aws/lambda/atlasretail-test-control"},
    "pipeline_alarm_name": {"value": "atlasretail-test-pipeline-failed"},
    "kms_alias_name": {"value": "alias/atlasretail-test"},
    "kms_key_arn": {"value": "arn:aws:kms:ap-south-1:887720497919:key/test"},
}


def verifier() -> ModuleType:
    """Return the imported script module."""
    return MODULE


def clean_runner(*arguments: str) -> tuple[int, str]:
    """Simulate explicit absence plus a key proven pending deletion."""
    command = " ".join(arguments)
    if "s3api head-bucket" in command:
        return 255, "An error occurred (404) when calling HeadBucket"
    if "dynamodb describe-table" in command:
        return 254, "ResourceNotFoundException"
    if "glue get-job" in command or "glue get-database" in command:
        return 254, "EntityNotFoundException"
    if "athena get-work-group" in command:
        return 254, "WorkGroup not found"
    if "lambda get-function" in command:
        return 254, "ResourceNotFoundException"
    if "stepfunctions describe-state-machine" in command:
        return 254, "StateMachineDoesNotExist"
    if "iam get-role" in command:
        return 254, "NoSuchEntity"
    if "logs describe-log-groups" in command:
        return 0, json.dumps({"logGroups": []})
    if "cloudwatch describe-alarms" in command:
        return 0, json.dumps({"MetricAlarms": [], "CompositeAlarms": []})
    if "kms list-aliases" in command:
        return 0, json.dumps({"Aliases": []})
    if "kms describe-key" in command:
        return 0, json.dumps(
            {
                "KeyMetadata": {
                    "KeyState": "PendingDeletion",
                    "DeletionDate": "2026-08-21T00:00:00Z",
                }
            }
        )
    if "sts get-caller-identity" in command:
        return 0, json.dumps({"Account": "887720497919"})
    if arguments[0] == "terraform":
        return 0, json.dumps({"format_version": "1.0"})
    if "resourcegroupstaggingapi" in command:
        return 0, json.dumps(
            {"ResourceTagMappingList": [{"ResourceARN": OUTPUTS["kms_key_arn"]["value"]}]}
        )
    raise AssertionError(f"unexpected command: {command}")


def test_clean_teardown_passes_with_only_proven_pending_kms_key() -> None:
    result = verifier().verify(OUTPUTS, "infra/atlas", "123", clean_runner)

    assert result["result"] == "PASS"
    assert len(result["checks"]) == 20
    assert all(check["deleted"] for check in result["checks"])


def test_active_kms_key_fails_and_is_not_allowed_by_tag_inventory() -> None:
    def active_key_runner(*arguments: str) -> tuple[int, str]:
        if "kms describe-key" in " ".join(arguments):
            return 0, json.dumps({"KeyMetadata": {"KeyState": "Enabled"}})
        return clean_runner(*arguments)

    result = verifier().verify(OUTPUTS, "infra/atlas", "123", active_key_runner)

    key_check = next(
        check for check in result["checks"] if check["resource"] == OUTPUTS["kms_key_arn"]["value"]
    )
    inventory = next(
        check for check in result["checks"] if check["resource"] == "RunId=123 tag inventory"
    )
    assert result["result"] == "FAIL"
    assert key_check["deleted"] is False
    assert inventory["deleted"] is False


def test_access_denied_fails_closed() -> None:
    def access_denied_runner(*arguments: str) -> tuple[int, str]:
        if arguments[0] == "terraform":
            return 0, json.dumps({"format_version": "1.0"})
        if "resourcegroupstaggingapi" in " ".join(arguments):
            return 0, json.dumps({"ResourceTagMappingList": []})
        return 254, "AccessDeniedException: not authorized"

    result = verifier().verify(OUTPUTS, "infra/atlas", "123", access_denied_runner)

    assert result["result"] == "FAIL"
    assert not all(check["deleted"] for check in result["checks"])


def test_remaining_resources_fail_all_inventory_layers() -> None:
    def residue_runner(*arguments: str) -> tuple[int, str]:
        command = " ".join(arguments)
        if arguments[0] == "terraform":
            return 0, json.dumps(
                {"values": {"root_module": {"resources": [{"address": "aws_s3_bucket.x"}]}}}
            )
        if "resourcegroupstaggingapi" in command:
            return 0, json.dumps(
                {
                    "ResourceTagMappingList": [
                        {
                            "ResourceARN": (
                                "arn:aws:dynamodb:ap-south-1:887720497919:table/atlasretail-residue"
                            )
                        }
                    ]
                }
            )
        return 0, "resource exists"

    result = verifier().verify(OUTPUTS, "infra/atlas", "123", residue_runner)

    state_check = next(
        check for check in result["checks"] if check["resource"] == "terraform-state"
    )
    assert result["result"] == "FAIL"
    assert state_check["deleted"] is False
    assert "aws_s3_bucket.x" in state_check["detail"]


def test_unreadable_terraform_state_fails_closed() -> None:
    def unreadable_state_runner(*arguments: str) -> tuple[int, str]:
        if arguments[0] == "terraform":
            return 1, "backend unavailable"
        return clean_runner(*arguments)

    result = verifier().verify(OUTPUTS, "infra/atlas", "123", unreadable_state_runner)

    state_check = next(
        check for check in result["checks"] if check["resource"] == "terraform-state"
    )
    assert result["result"] == "FAIL"
    assert state_check["deleted"] is False


def test_missing_outputs_still_checks_fallback_names_state_and_tags() -> None:
    calls: list[tuple[str, ...]] = []

    def recording_runner(*arguments: str) -> tuple[int, str]:
        calls.append(arguments)
        return clean_runner(*arguments)

    result = verifier().verify({}, "infra/atlas", "123", recording_runner)

    assert result["result"] == "FAIL"
    assert any("atlasretail-123-control" in call for call in calls)
    assert any(call[0] == "terraform" for call in calls)
    assert any("resourcegroupstaggingapi" in call for call in calls)


def test_exact_log_group_match_fails() -> None:
    target = OUTPUTS["glue_log_group_name"]["value"]

    def log_residue_runner(*arguments: str) -> tuple[int, str]:
        command = " ".join(arguments)
        if "logs describe-log-groups" in command and target in arguments:
            return 0, json.dumps({"logGroups": [{"logGroupName": target}]})
        return clean_runner(*arguments)

    result = verifier().verify(OUTPUTS, "infra/atlas", "123", log_residue_runner)

    log_check = next(check for check in result["checks"] if check["resource"] == target)
    assert result["result"] == "FAIL"
    assert log_check["deleted"] is False


def test_malformed_success_response_fails_closed() -> None:
    def malformed_runner(*arguments: str) -> tuple[int, str]:
        if "logs describe-log-groups" in " ".join(arguments):
            return 0, "not-json"
        return clean_runner(*arguments)

    result = verifier().verify(OUTPUTS, "infra/atlas", "123", malformed_runner)

    assert result["result"] == "FAIL"
