from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

EVIDENCE = Path(__file__).parents[1] / "evidence" / "aws" / "recovery" / "32952618876"
SUMMARY_FILES = {"destroy-plan-summary.json", "teardown-summary.json", "execution-status.json"}


def load(name: str) -> dict[str, Any]:
    value = json.loads((EVIDENCE / name).read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def test_recovery_evidence_is_attributed_and_digest_verified() -> None:
    manifest = load("manifest.json")

    assert manifest["result"] == "PASS"
    assert manifest["run_id"] == 32952618876
    assert manifest["source_commit"] == "61abca2553fed7982db3aff8046687d718ef4142"
    assert manifest["permission_fix_merge_commit"] == ("310047c068d5d1b55ea0a1a8ec0ba8eb84f4dce9")
    assert manifest["aws_account_id"] == "857229544428"
    assert manifest["aws_region"] == "ap-southeast-2"
    assert manifest["artifact"] == {
        "created_at": "2026-08-27T03:49:01Z",
        "id": 9632545805,
        "name": "atlasretail-aws-evidence-32952618876",
        "sha256": "300ac7e5fa122e39f8cdad93a5891e3ef4be869723c00e830c6f1abfdd32695c",
        "size_bytes": 79257,
    }
    assert manifest["original_execute_job_id"] == 98127242602
    assert manifest["original_teardown_job_id"] == 98128935020
    assert manifest["successful_teardown_job_id"] == 98402942900
    assert manifest["source_evidence_sha256"] == {
        "summary.json": "0f6ef8e71ca657017a4bfc47b8abc427be6c383c903ee3076b0c4e6224ac38f8",
        "teardown.json": "cdd4d0fd0dc6dcc2b2704f994ce4aa3b35b65f48c7b61ac8654c5d348b20627c",
        "terraform-destroy-plan-validation.json": (
            "11b89c372d77f3c3248652188a806f4e975c1c0bde91bfaf622ff89c2e0a60aa"
        ),
        "terraform-outputs.json": (
            "6ebf58ee3f9d146eebd14c040d6a982e7e0e691642360fa0ac2faf0cf03a7ca0"
        ),
    }
    assert set(manifest["committed_summaries"]) == SUMMARY_FILES
    assert {path.name for path in EVIDENCE.iterdir()} == SUMMARY_FILES | {"manifest.json"}

    for name, expected_digest in manifest["committed_summaries"].items():
        digest = hashlib.sha256((EVIDENCE / name).read_bytes()).hexdigest()
        assert digest == expected_digest


def test_recovery_proves_cleanup_without_promoting_execution() -> None:
    plan = load("destroy-plan-summary.json")
    teardown = load("teardown-summary.json")
    execution = load("execution-status.json")

    assert plan["result"] == "PASS"
    assert plan["mode"] == "destroy"
    assert plan["resource_count"] == 39
    assert plan["read_only_data_source_counts"] == {}
    assert plan["errors"] == []

    assert teardown["result"] == "PASS"
    assert teardown["account"] == "857229544428"
    assert teardown["region"] == "ap-southeast-2"
    assert teardown["checks"]["terraform_state_empty"] is True
    assert teardown["checks"]["unexpected_run_tagged_resources"] == []
    assert teardown["kms_key_disposition"] == {
        "deletion_date_verified": True,
        "status": "PENDING_DELETION",
    }
    assert teardown["account_lease_released"] is True
    assert teardown["errors"] == []

    assert execution["result"] == "RECOVERED"
    assert execution["claim_level"] == "AWS_EXECUTION_INCOMPLETE"
    assert execution["bounded_deployment_verified"] is False
    assert execution["managed_data_path_verified"] is False
    assert execution["production_claim"] is False
    assert execution["recovery_and_teardown_verified"] is True
    assert execution["metered_usage"] == {
        "athena_bytes_scanned": 0,
        "athena_queries": 0,
        "glue_dpu_seconds": 0.0,
        "glue_job_runs": 0,
    }
    assert execution["immediate_cost_estimate_usd"]["partial_total"] == 0.0
