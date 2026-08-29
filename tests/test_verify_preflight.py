"""Tests for the fail-closed clean-account preflight."""

from __future__ import annotations

import importlib.util
import json
import time
from pathlib import Path

SCRIPT = Path(__file__).parents[1] / "scripts" / "verify_preflight.py"
SPEC = importlib.util.spec_from_file_location("verify_preflight", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)

PENDING_KEY = "arn:aws:kms:ap-southeast-2:857229544428:key/historical"
LEASE_TABLE = "portfolio-lab-account-lease"


def clean_runner(*arguments: str) -> tuple[int, str]:
    command = " ".join(arguments)
    if arguments[0] == "terraform":
        return 0, json.dumps({"format_version": "1.0"})
    if "dynamodb get-item" in command:
        return 0, ""
    if "resourcegroupstaggingapi" in command:
        return 0, json.dumps({"ResourceTagMappingList": [{"ResourceARN": PENDING_KEY}]})
    if "kms describe-key" in command:
        return 0, json.dumps(
            {
                "KeyMetadata": {
                    "KeyState": "PendingDeletion",
                    "DeletionDate": "2026-08-21T00:00:00Z",
                }
            }
        )
    if "kms list-aliases" in command:
        return 0, json.dumps({"Aliases": []})
    raise AssertionError(command)


def test_empty_state_and_historical_pending_key_pass(monkeypatch: object) -> None:
    monkeypatch.setattr(MODULE, "command", clean_runner)

    result = MODULE.verify("infra/atlas", LEASE_TABLE)

    assert result["result"] == "PASS"
    assert result["account_lease_table"] == LEASE_TABLE
    assert result["account_lease_read_exit_code"] == 0
    assert result["account_lease_absent"] is True
    assert result["account_lease_item"] is None
    assert result["allowed_pending_deletion_kms_keys"] == [PENDING_KEY]
    assert result["pending_deletion_kms_aliases"] == {PENDING_KEY: []}
    assert result["kms_inspection_errors"] == []


def test_live_tagged_resource_fails(monkeypatch: object) -> None:
    def live_runner(*arguments: str) -> tuple[int, str]:
        if "resourcegroupstaggingapi" in " ".join(arguments):
            return 0, json.dumps(
                {"ResourceTagMappingList": [{"ResourceARN": "arn:aws:s3:::atlasretail-leftover"}]}
            )
        return clean_runner(*arguments)

    monkeypatch.setattr(MODULE, "command", live_runner)

    result = MODULE.verify("infra/atlas", LEASE_TABLE)

    assert result["result"] == "FAIL"
    assert result["unexpected_resources"] == ["arn:aws:s3:::atlasretail-leftover"]


def test_nonempty_remote_state_fails(monkeypatch: object) -> None:
    def state_runner(*arguments: str) -> tuple[int, str]:
        if arguments[0] == "terraform":
            return 0, json.dumps(
                {"values": {"root_module": {"resources": [{"address": "aws_s3_bucket.old"}]}}}
            )
        return clean_runner(*arguments)

    monkeypatch.setattr(MODULE, "command", state_runner)

    result = MODULE.verify("infra/atlas", LEASE_TABLE)

    assert result["result"] == "FAIL"
    assert result["terraform_state_resources"] == ["aws_s3_bucket.old"]


def test_pending_deletion_key_with_alias_fails(monkeypatch: object) -> None:
    def alias_runner(*arguments: str) -> tuple[int, str]:
        if "kms list-aliases" in " ".join(arguments):
            return 0, json.dumps({"Aliases": [{"AliasName": "alias/atlasretail-old"}]})
        return clean_runner(*arguments)

    monkeypatch.setattr(MODULE, "command", alias_runner)

    result = MODULE.verify("infra/atlas", LEASE_TABLE)

    assert result["result"] == "FAIL"
    assert result["unexpected_resources"] == [PENDING_KEY]
    assert result["pending_deletion_kms_aliases"] == {PENDING_KEY: ["alias/atlasretail-old"]}
    assert result["kms_inspection_errors"] == [f"{PENDING_KEY}: aliases remain attached"]


def test_unreadable_pending_deletion_aliases_fail(monkeypatch: object) -> None:
    def unreadable_alias_runner(*arguments: str) -> tuple[int, str]:
        if "kms list-aliases" in " ".join(arguments):
            return 254, "AccessDeniedException"
        return clean_runner(*arguments)

    monkeypatch.setattr(MODULE, "command", unreadable_alias_runner)

    result = MODULE.verify("infra/atlas", LEASE_TABLE)

    assert result["result"] == "FAIL"
    assert result["unexpected_resources"] == [PENDING_KEY]
    assert result["kms_inspection_errors"] == [f"{PENDING_KEY}: aliases are unreadable"]


def test_unreadable_kms_metadata_fails(monkeypatch: object) -> None:
    def unreadable_key_runner(*arguments: str) -> tuple[int, str]:
        if "kms describe-key" in " ".join(arguments):
            return 254, "AccessDeniedException"
        return clean_runner(*arguments)

    monkeypatch.setattr(MODULE, "command", unreadable_key_runner)

    result = MODULE.verify("infra/atlas", LEASE_TABLE)

    assert result["result"] == "FAIL"
    assert result["unexpected_resources"] == [PENDING_KEY]
    assert result["kms_inspection_errors"] == [f"{PENDING_KEY}: key metadata is unreadable"]


def test_pending_deletion_without_date_fails(monkeypatch: object) -> None:
    def missing_date_runner(*arguments: str) -> tuple[int, str]:
        if "kms describe-key" in " ".join(arguments):
            return 0, json.dumps({"KeyMetadata": {"KeyState": "PendingDeletion"}})
        return clean_runner(*arguments)

    monkeypatch.setattr(MODULE, "command", missing_date_runner)

    result = MODULE.verify("infra/atlas", LEASE_TABLE)

    assert result["result"] == "FAIL"
    assert result["unexpected_resources"] == [PENDING_KEY]
    assert result["kms_inspection_errors"] == [
        f"{PENDING_KEY}: key is not a verifiable pending-deletion exception"
    ]


def test_unreadable_tag_inventory_fails(monkeypatch: object) -> None:
    def unreadable_inventory_runner(*arguments: str) -> tuple[int, str]:
        if "resourcegroupstaggingapi" in " ".join(arguments):
            return 254, "AccessDeniedException"
        return clean_runner(*arguments)

    monkeypatch.setattr(MODULE, "command", unreadable_inventory_runner)

    result = MODULE.verify("infra/atlas", LEASE_TABLE)

    assert result["result"] == "FAIL"
    assert "AtlasRetail tag inventory is unreadable" in result["errors"]


def test_live_account_lease_fails(monkeypatch: object) -> None:
    lease = {
        "lock_id": {"S": "portfolio-lab"},
        "owner": {"S": "recovery/33252972714"},
        "expires_at": {"N": "1788009000"},
    }

    def held_lease_runner(*arguments: str) -> tuple[int, str]:
        if "dynamodb get-item" in " ".join(arguments):
            return 0, json.dumps({"Item": lease})
        return clean_runner(*arguments)

    monkeypatch.setattr(MODULE, "command", held_lease_runner)

    result = MODULE.verify("infra/atlas", LEASE_TABLE)

    assert result["result"] == "FAIL"
    assert result["account_lease_absent"] is False
    assert result["account_lease_item"] == lease
    assert "Account-wide lease is still held" in result["errors"]


def test_exact_unexpired_expected_account_lease_passes(monkeypatch: object) -> None:
    expected_owner = "bhuvaneshwaranmurugan21/atlasretail-lakehouse-platform/123"
    expiry = int(time.time()) + 300

    def owned_lease_runner(*arguments: str) -> tuple[int, str]:
        if "dynamodb get-item" in " ".join(arguments):
            return 0, json.dumps(
                {
                    "Item": {
                        "lock_id": {"S": "portfolio-lab"},
                        "owner": {"S": expected_owner},
                        "expires_at": {"N": str(expiry)},
                    }
                }
            )
        return clean_runner(*arguments)

    monkeypatch.setattr(MODULE, "command", owned_lease_runner)

    result = MODULE.verify("infra/atlas", LEASE_TABLE, expected_owner)

    assert result["result"] == "PASS"
    assert result["account_lease_absent"] is False
    assert result["account_lease_expected_owner"] == expected_owner
    assert result["account_lease_owner"] == expected_owner
    assert result["account_lease_expires_at"] == expiry
    assert result["account_lease_ownership_verified"] is True


def test_wrong_expected_account_lease_owner_fails(monkeypatch: object) -> None:
    def wrong_owner_runner(*arguments: str) -> tuple[int, str]:
        if "dynamodb get-item" in " ".join(arguments):
            return 0, json.dumps(
                {
                    "Item": {
                        "lock_id": {"S": "portfolio-lab"},
                        "owner": {"S": "other/repository/456"},
                        "expires_at": {"N": str(int(time.time()) + 300)},
                    }
                }
            )
        return clean_runner(*arguments)

    monkeypatch.setattr(MODULE, "command", wrong_owner_runner)

    result = MODULE.verify("infra/atlas", LEASE_TABLE, "expected/repository/123")

    assert result["result"] == "FAIL"
    assert result["account_lease_ownership_verified"] is False
    assert "Account-wide lease does not match the expected live owner" in result["errors"]


def test_expired_expected_account_lease_fails(monkeypatch: object) -> None:
    expected_owner = "expected/repository/123"

    def expired_lease_runner(*arguments: str) -> tuple[int, str]:
        if "dynamodb get-item" in " ".join(arguments):
            return 0, json.dumps(
                {
                    "Item": {
                        "lock_id": {"S": "portfolio-lab"},
                        "owner": {"S": expected_owner},
                        "expires_at": {"N": str(int(time.time()) - 1)},
                    }
                }
            )
        return clean_runner(*arguments)

    monkeypatch.setattr(MODULE, "command", expired_lease_runner)

    result = MODULE.verify("infra/atlas", LEASE_TABLE, expected_owner)

    assert result["result"] == "FAIL"
    assert result["account_lease_ownership_verified"] is False
    assert "Account-wide lease does not match the expected live owner" in result["errors"]


def test_missing_expected_account_lease_fails(monkeypatch: object) -> None:
    monkeypatch.setattr(MODULE, "command", clean_runner)

    result = MODULE.verify("infra/atlas", LEASE_TABLE, "expected/repository/123")

    assert result["result"] == "FAIL"
    assert result["account_lease_absent"] is True
    assert result["account_lease_ownership_verified"] is False
    assert "Expected account-wide lease is absent" in result["errors"]


def test_unreadable_account_lease_fails(monkeypatch: object) -> None:
    def unreadable_lease_runner(*arguments: str) -> tuple[int, str]:
        if "dynamodb get-item" in " ".join(arguments):
            return 254, "AccessDeniedException"
        return clean_runner(*arguments)

    monkeypatch.setattr(MODULE, "command", unreadable_lease_runner)

    result = MODULE.verify("infra/atlas", LEASE_TABLE)

    assert result["result"] == "FAIL"
    assert result["account_lease_absent"] is False
    assert result["account_lease_read_exit_code"] == 254
    assert result["account_lease_item"] is None
    assert "Account-wide lease is unreadable" in result["errors"]


def test_malformed_successful_account_lease_response_fails(monkeypatch: object) -> None:
    def malformed_lease_runner(*arguments: str) -> tuple[int, str]:
        if "dynamodb get-item" in " ".join(arguments):
            return 0, "not-json"
        return clean_runner(*arguments)

    monkeypatch.setattr(MODULE, "command", malformed_lease_runner)

    result = MODULE.verify("infra/atlas", LEASE_TABLE)

    assert result["result"] == "FAIL"
    assert result["account_lease_read_exit_code"] == 0
    assert result["account_lease_absent"] is False
    assert "Account-wide lease response is malformed" in result["errors"]
