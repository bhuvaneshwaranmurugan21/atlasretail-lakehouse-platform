"""Tests for attempt-bound Part 4 lease transitions."""

from __future__ import annotations

import importlib.util
from argparse import Namespace
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).parents[1]
SPEC = importlib.util.spec_from_file_location(
    "manage_part4_lease", ROOT / "scripts/manage_part4_lease.py"
)
assert SPEC and SPEC.loader
LEASE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(LEASE)

OWNER = "bhuvaneshwaranmurugan21/atlasretail-lakehouse-platform/424242/3"
SOURCE = "a" * 40
AUTHORITY = "b" * 64


def args(**overrides: object) -> Namespace:
    values: dict[str, object] = {
        "table": "portfolio-lab-account-lease",
        "region": "ap-southeast-2",
        "owner": OWNER,
        "run_attempt": "3",
        "source_commit": SOURCE,
        "contract_sha256": "c" * 64,
        "target_sha256": "d" * 64,
        "authority_sha256": AUTHORITY,
        "artifact_id": "12345",
        "artifact_digest": "sha256:" + "e" * 64,
        "expected_state": "AUTHORITY_BOUND",
        "recovery_owner": "recovery/999",
    }
    values.update(overrides)
    return Namespace(**values)


def item(owner: str = OWNER, state: str = "AUTHORITY_BOUND") -> dict[str, Any]:
    return {
        "lock_id": {"S": "portfolio-lab"},
        "owner": {"S": owner},
        "run_attempt": {"S": "3"},
        "source_commit": {"S": SOURCE},
        "contract_sha256": {"S": "c" * 64},
        "target_sha256": {"S": "d" * 64},
        "authority_sha256": {"S": AUTHORITY},
        "authority_artifact_id": {"S": "12345"},
        "authority_artifact_digest": {"S": "sha256:" + "e" * 64},
        "state": {"S": state},
        "expires_at": {"N": "9999999999"},
    }


def test_acquire_never_uses_expiry_as_takeover_authority(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[list[str]] = []
    monkeypatch.setattr(LEASE, "aws", lambda value: calls.append(value) or {})
    monkeypatch.setattr(
        LEASE,
        "consistent_item",
        lambda _table, _region: item(state="ACQUIRED"),
    )

    proof = LEASE.acquire(args())

    assert proof["result"] == "PASS"
    assert proof["silent_expiry_takeover"] is False
    command = calls[0]
    condition = command[command.index("--condition-expression") + 1]
    assert condition == "attribute_not_exists(lock_id)"
    assert "expires_at <" not in condition


def test_bind_is_conditional_on_owner_attempt_source_and_unbound_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[list[str]] = []
    monkeypatch.setattr(LEASE, "aws", lambda value: calls.append(value) or {})
    monkeypatch.setattr(LEASE, "consistent_item", lambda _table, _region: item())

    proof = LEASE.bind(args())

    assert proof["state"] == "AUTHORITY_BOUND"
    assert proof["authority_sha256"] == AUTHORITY
    command = calls[0]
    condition = command[command.index("--condition-expression") + 1]
    assert "#owner = :owner" in condition
    assert "run_attempt = :attempt" in condition
    assert "source_commit = :source" in condition
    assert "attribute_not_exists(authority_sha256)" in condition


def test_consistent_verification_rejects_authority_substitution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    wrong = item()
    wrong["authority_sha256"] = {"S": "0" * 64}
    monkeypatch.setattr(LEASE, "consistent_item", lambda _table, _region: wrong)

    with pytest.raises(LEASE.LeaseError, match="authority digest differs"):
        LEASE.verify(args())


def test_pre_authority_verification_requires_exact_acquired_lease(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    acquired = item(state="ACQUIRED")
    acquired.pop("authority_sha256")
    acquired.pop("authority_artifact_id")
    acquired.pop("authority_artifact_digest")
    monkeypatch.setattr(LEASE, "consistent_item", lambda _table, _region: acquired)

    proof = LEASE.verify_acquired(args())

    assert proof["state"] == "ACQUIRED"
    assert proof["authority_absent"] is True
    assert proof["contract_sha256"] == "c" * 64


def test_pre_authority_verification_rejects_any_authority(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        LEASE,
        "consistent_item",
        lambda _table, _region: item(state="ACQUIRED"),
    )
    with pytest.raises(LEASE.LeaseError, match="unexpectedly contains"):
        LEASE.verify_acquired(args())


def test_recovery_transitions_only_the_exact_failed_owner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[list[str]] = []
    monkeypatch.setattr(LEASE, "aws", lambda value: calls.append(value) or {})
    monkeypatch.setattr(
        LEASE,
        "consistent_item",
        lambda _table, _region: item(owner="recovery/999", state="RECOVERY_BOUND"),
    )

    proof = LEASE.recover(args())

    assert proof["mode"] == "EXACT_OWNER_TRANSITION"
    condition = calls[0][calls[0].index("--condition-expression") + 1]
    assert "#owner = :failed_owner" in condition
    assert "authority_sha256 = :authority" in condition
    assert proof["owner"] == "recovery/999"


def test_absent_recovery_uses_conditional_acquisition_not_overwrite(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[list[str]] = []

    def fake_aws(value: list[str]) -> dict[str, Any]:
        calls.append(value)
        if len(calls) == 1:
            raise LEASE.LeaseError("ConditionalCheckFailedException")
        return {}

    monkeypatch.setattr(LEASE, "aws", fake_aws)
    monkeypatch.setattr(
        LEASE,
        "consistent_item",
        lambda _table, _region: item(owner="recovery/999", state="RECOVERY_BOUND"),
    )

    proof = LEASE.recover(args())

    assert proof["mode"] == "ABSENT_LEASE_RECOVERY_ACQUISITION"
    condition = calls[1][calls[1].index("--condition-expression") + 1]
    assert condition == "attribute_not_exists(lock_id)"
