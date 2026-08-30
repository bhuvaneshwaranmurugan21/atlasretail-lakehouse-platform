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


def completed(stdout: object, code: int = 0) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(
        args=["aws"], returncode=code, stdout=json.dumps(stdout), stderr=""
    )


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
