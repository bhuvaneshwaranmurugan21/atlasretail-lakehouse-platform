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
    "state_machine_arn": {"value": "arn:aws:states:ap-south-1:887720497919:stateMachine:test"},
    "kms_key_arn": {"value": "arn:aws:kms:ap-south-1:887720497919:key/test"},
}


def verifier() -> ModuleType:
    """Return the imported script module."""
    return MODULE


def clean_runner(*arguments: str) -> tuple[int, str]:
    """Simulate explicit absence plus the permitted scheduled KMS key."""
    command = " ".join(arguments)
    if "s3api head-bucket" in command:
        return 255, "An error occurred (404) when calling HeadBucket: Not Found"
    if "dynamodb describe-table" in command:
        return 254, "ResourceNotFoundException"
    if "glue get-job" in command:
        return 254, "EntityNotFoundException"
    if "stepfunctions describe-state-machine" in command:
        return 254, "StateMachineDoesNotExist"
    if "terraform" in arguments[0]:
        return 0, json.dumps({"format_version": "1.0"})
    if "resourcegroupstaggingapi" in command:
        return 0, json.dumps(
            {"ResourceTagMappingList": [{"ResourceARN": OUTPUTS["kms_key_arn"]["value"]}]}
        )
    raise AssertionError(f"unexpected command: {command}")


def test_clean_teardown_passes_with_only_scheduled_kms_key() -> None:
    result = verifier().verify(OUTPUTS, "infra/atlas", "123", clean_runner)

    assert result["result"] == "PASS"
    assert len(result["checks"]) == 8
    assert all(check["deleted"] for check in result["checks"])


def test_access_denied_fails_closed() -> None:
    def access_denied_runner(*arguments: str) -> tuple[int, str]:
        command = " ".join(arguments)
        if "terraform" in arguments[0]:
            return 0, json.dumps({"format_version": "1.0"})
        if "resourcegroupstaggingapi" in command:
            return 0, json.dumps({"ResourceTagMappingList": []})
        return 254, "AccessDeniedException: not authorized"

    result = verifier().verify(OUTPUTS, "infra/atlas", "123", access_denied_runner)

    assert result["result"] == "FAIL"
    assert not all(check["deleted"] for check in result["checks"])


def test_remaining_resources_fail_all_three_inventory_layers() -> None:
    def residue_runner(*arguments: str) -> tuple[int, str]:
        command = " ".join(arguments)
        if "terraform" in arguments[0]:
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

    assert result["result"] == "FAIL"
    assert not any(check["deleted"] for check in result["checks"])


def test_unreadable_terraform_state_fails_closed() -> None:
    def unreadable_state_runner(*arguments: str) -> tuple[int, str]:
        if "terraform" in arguments[0]:
            return 1, "backend unavailable"
        return clean_runner(*arguments)

    result = verifier().verify(OUTPUTS, "infra/atlas", "123", unreadable_state_runner)

    state_check = next(
        check for check in result["checks"] if check["resource"] == "terraform-state"
    )
    assert result["result"] == "FAIL"
    assert state_check["deleted"] is False


def test_missing_outputs_still_checks_state_and_tag_inventory() -> None:
    calls: list[tuple[str, ...]] = []

    def recording_runner(*arguments: str) -> tuple[int, str]:
        calls.append(arguments)
        if "terraform" in arguments[0]:
            return 0, json.dumps({"format_version": "1.0"})
        if "resourcegroupstaggingapi" in " ".join(arguments):
            return 0, json.dumps({"ResourceTagMappingList": []})
        raise AssertionError(f"unexpected command: {' '.join(arguments)}")

    result = verifier().verify({}, "infra/atlas", "123", recording_runner)

    assert result["result"] == "FAIL"
    assert any("terraform" in call[0] for call in calls)
    assert any("resourcegroupstaggingapi" in call for call in calls)
