from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

EVIDENCE = Path(__file__).parents[1] / "evidence" / "aws" / "foundation" / "32926893305"
SUMMARY_FILES = {
    "foundation-verification.json",
    "iam-parity.json",
    "zero-workload-preflight.json",
    "lease-contention.json",
    "lease-release.json",
}


def load(name: str) -> dict[str, Any]:
    value = json.loads((EVIDENCE / name).read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def test_foundation_evidence_is_attributed_and_digest_verified() -> None:
    manifest = load("manifest.json")

    assert manifest["result"] == "PASS"
    assert manifest["run_id"] == 32926893305
    assert manifest["run_number"] == 9
    assert manifest["source_commit"] == "5a420249e5314c41202d066fad8f6a7682c447b3"
    assert manifest["aws_account_id"] == "857229544428"
    assert manifest["aws_region"] == "ap-southeast-2"
    assert set(manifest["committed_summaries"]) == SUMMARY_FILES
    assert {path.name for path in EVIDENCE.iterdir()} == SUMMARY_FILES | {"manifest.json"}

    for name, expected_digest in manifest["committed_summaries"].items():
        digest = hashlib.sha256((EVIDENCE / name).read_bytes()).hexdigest()
        assert digest == expected_digest


def test_foundation_evidence_proves_the_required_gate() -> None:
    foundation = load("foundation-verification.json")
    iam = load("iam-parity.json")
    preflight = load("zero-workload-preflight.json")
    contention = load("lease-contention.json")
    release = load("lease-release.json")

    assert foundation["result"] == "PASS"
    assert foundation["errors"] == []
    assert foundation["stack_status"] == "CREATE_COMPLETE"
    assert foundation["budget_notification_count"] == 3
    assert foundation["zero_workload_verified"] is True
    assert foundation["lease_contention_blocked"] is True
    assert foundation["lease_owner_release_verified"] is True
    assert iam["result"] == "PASS"
    assert iam["tracked_policy_matches_live"] is True
    assert iam["no_attached_managed_policies"] is True
    assert preflight == {
        "allowed_pending_deletion_kms_keys": [],
        "errors": [],
        "result": "PASS",
        "terraform_state_resources": [],
        "unexpected_resources": [],
    }
    assert contention == {"result": "PASS", "contention_blocked": True}
    assert release == {"owner_scoped_release": True, "result": "PASS"}
