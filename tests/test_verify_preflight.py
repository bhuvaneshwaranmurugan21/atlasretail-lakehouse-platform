"""Tests for the fail-closed clean-account preflight."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

SCRIPT = Path(__file__).parents[1] / "scripts" / "verify_preflight.py"
SPEC = importlib.util.spec_from_file_location("verify_preflight", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)

PENDING_KEY = "arn:aws:kms:ap-southeast-2:857229544428:key/historical"


def clean_runner(*arguments: str) -> tuple[int, str]:
    command = " ".join(arguments)
    if arguments[0] == "terraform":
        return 0, json.dumps({"format_version": "1.0"})
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
    raise AssertionError(command)


def test_empty_state_and_historical_pending_key_pass(monkeypatch: object) -> None:
    monkeypatch.setattr(MODULE, "command", clean_runner)

    result = MODULE.verify("infra/atlas")

    assert result["result"] == "PASS"
    assert result["allowed_pending_deletion_kms_keys"] == [PENDING_KEY]


def test_live_tagged_resource_fails(monkeypatch: object) -> None:
    def live_runner(*arguments: str) -> tuple[int, str]:
        if "resourcegroupstaggingapi" in " ".join(arguments):
            return 0, json.dumps(
                {"ResourceTagMappingList": [{"ResourceARN": "arn:aws:s3:::atlasretail-leftover"}]}
            )
        return clean_runner(*arguments)

    monkeypatch.setattr(MODULE, "command", live_runner)

    result = MODULE.verify("infra/atlas")

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

    result = MODULE.verify("infra/atlas")

    assert result["result"] == "FAIL"
    assert result["terraform_state_resources"] == ["aws_s3_bucket.old"]
