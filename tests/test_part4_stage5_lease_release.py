"""Exact-condition and consistent-read tests for Part 4 lease release."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
SPEC = importlib.util.spec_from_file_location(
    "verify_lease_release", ROOT / "scripts/verify_lease_release.py"
)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)

OWNER = "bhuvaneshwaranmurugan21/atlasretail-lakehouse-platform/123/2"
AUTHORITY = "a" * 64
SOURCE = "b" * 40
CONTRACT = "c" * 64
TARGET = "d" * 64


def completed(stdout: object, code: int = 0) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(
        args=["aws"], returncode=code, stdout=json.dumps(stdout), stderr=""
    )


def completed_raw(stdout: str, code: int = 0) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(args=["aws"], returncode=code, stdout=stdout, stderr="")


def arguments(output: Path) -> list[str]:
    return [
        "verify_lease_release.py",
        "--table",
        "portfolio-lab-account-lease",
        "--owner",
        OWNER,
        "--region",
        "ap-southeast-2",
        "--authority-sha256",
        AUTHORITY,
        "--run-attempt",
        "2",
        "--source-commit",
        SOURCE,
        "--output",
        str(output),
    ]


def deleted_item(authority: str = AUTHORITY) -> dict[str, object]:
    return {
        "Attributes": {
            "owner": {"S": OWNER},
            "authority_sha256": {"S": authority},
            "run_attempt": {"S": "2"},
            "source_commit": {"S": SOURCE},
        }
    }


def lease_only_arguments(output: Path) -> list[str]:
    return [
        "verify_lease_release.py",
        "--table",
        "portfolio-lab-account-lease",
        "--owner",
        OWNER,
        "--region",
        "ap-southeast-2",
        "--run-attempt",
        "2",
        "--source-commit",
        SOURCE,
        "--contract-sha256",
        CONTRACT,
        "--target-sha256",
        TARGET,
        "--expected-state",
        "ACQUIRED",
        "--output",
        str(output),
    ]


def idempotent_lease_only_arguments(output: Path) -> list[str]:
    values = lease_only_arguments(output)
    values.insert(-2, "--allow-absent")
    return values


def lease_only_deleted_item(state: str = "ACQUIRED") -> dict[str, object]:
    return {
        "Attributes": {
            "owner": {"S": OWNER},
            "run_attempt": {"S": "2"},
            "source_commit": {"S": SOURCE},
            "contract_sha256": {"S": CONTRACT},
            "target_sha256": {"S": TARGET},
            "state": {"S": state},
        }
    }


def test_release_conditions_every_immutable_owner_field_and_proves_absence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[list[str]] = []

    def run(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append(command)
        return completed(deleted_item()) if len(calls) == 1 else completed({})

    output = tmp_path / "release.json"
    monkeypatch.setattr(MODULE.subprocess, "run", run)
    monkeypatch.setattr(sys, "argv", arguments(output))

    assert MODULE.main() == 0
    condition = calls[0][calls[0].index("--condition-expression") + 1]
    assert condition == (
        "#owner = :owner AND authority_sha256 = :authority "
        "AND run_attempt = :attempt AND source_commit = :source"
    )
    assert "--consistent-read" in calls[1]
    proof = json.loads(output.read_text(encoding="utf-8"))
    assert proof["result"] == "PASS"
    assert proof["lease_absent"] is True


def test_release_rejects_substituted_returned_authority(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[list[str]] = []

    def run(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append(command)
        return completed(deleted_item("c" * 64))

    output = tmp_path / "release.json"
    monkeypatch.setattr(MODULE.subprocess, "run", run)
    monkeypatch.setattr(sys, "argv", arguments(output))

    assert MODULE.main() == 1
    assert len(calls) == 1
    assert json.loads(output.read_text(encoding="utf-8"))["result"] == "FAIL"


def test_release_rejects_lease_reappearance_after_delete(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    responses = iter((completed(deleted_item()), completed({"Item": {"owner": {"S": OWNER}}})))
    output = tmp_path / "release.json"
    monkeypatch.setattr(MODULE.subprocess, "run", lambda *_args, **_kwargs: next(responses))
    monkeypatch.setattr(sys, "argv", arguments(output))

    assert MODULE.main() == 1
    proof = json.loads(output.read_text(encoding="utf-8"))
    assert proof["lease_absent"] is False
    assert proof["post_delete_item"] == {"owner": {"S": OWNER}}


def test_pre_authority_release_conditions_contract_target_and_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[list[str]] = []

    def run(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append(command)
        return completed(lease_only_deleted_item()) if len(calls) == 1 else completed({})

    output = tmp_path / "lease-only-release.json"
    monkeypatch.setattr(MODULE.subprocess, "run", run)
    monkeypatch.setattr(sys, "argv", lease_only_arguments(output))

    assert MODULE.main() == 0
    condition = calls[0][calls[0].index("--condition-expression") + 1]
    assert "contract_sha256 = :contract" in condition
    assert "target_sha256 = :target" in condition
    assert "#state = :state" in condition
    assert json.loads(output.read_text(encoding="utf-8"))["result"] == "PASS"


def test_release_accepts_empty_cli_output_as_strongly_consistent_absence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    responses = iter((completed(lease_only_deleted_item()), completed_raw("")))
    output = tmp_path / "lease-only-release.json"
    monkeypatch.setattr(MODULE.subprocess, "run", lambda *_args, **_kwargs: next(responses))
    monkeypatch.setattr(sys, "argv", lease_only_arguments(output))

    assert MODULE.main() == 0
    proof = json.loads(output.read_text(encoding="utf-8"))
    assert proof["result"] == "PASS"
    assert proof["lease_absent"] is True
    assert proof["post_delete_item"] is None


def test_pre_authority_release_rejects_bound_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output = tmp_path / "lease-only-release.json"
    monkeypatch.setattr(
        MODULE.subprocess,
        "run",
        lambda *_args, **_kwargs: completed(lease_only_deleted_item("AUTHORITY_BOUND")),
    )
    monkeypatch.setattr(sys, "argv", lease_only_arguments(output))

    assert MODULE.main() == 1
    assert json.loads(output.read_text(encoding="utf-8"))["result"] == "FAIL"


def test_recovery_release_accepts_strongly_consistent_prior_absence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[list[str]] = []

    def run(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append(command)
        return completed({})

    output = tmp_path / "lease-only-release.json"
    monkeypatch.setattr(MODULE.subprocess, "run", run)
    monkeypatch.setattr(sys, "argv", idempotent_lease_only_arguments(output))

    assert MODULE.main() == 0
    assert len(calls) == 1
    assert "get-item" in calls[0]
    proof = json.loads(output.read_text(encoding="utf-8"))
    assert proof["result"] == "PASS"
    assert proof["already_absent"] is True
    assert proof["delete_attempted"] is False
    assert proof["lease_absent"] is True
