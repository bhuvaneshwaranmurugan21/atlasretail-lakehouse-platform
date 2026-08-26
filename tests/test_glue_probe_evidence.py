from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

EVIDENCE = Path(__file__).parents[1] / "evidence" / "aws" / "glue-probe" / "32930567869"
SUMMARY_FILES = {"glue-service-probe.json", "cleanup-verification.json"}


def load(name: str) -> dict[str, Any]:
    value = json.loads((EVIDENCE / name).read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def test_glue_probe_evidence_is_attributed_and_digest_verified() -> None:
    manifest = load("manifest.json")

    assert manifest["result"] == "PASS"
    assert manifest["run_id"] == 32930567869
    assert manifest["run_number"] == 2
    assert manifest["source_commit"] == "bca352732cb9e5d82627edc32321003ad5e0676e"
    assert manifest["aws_account_id"] == "857229544428"
    assert manifest["aws_region"] == "ap-southeast-2"
    assert manifest["artifact"]["sha256"] == (
        "768416fc1c1fbdc4c2b2cd40f7a1796ed519442a4205872b8d78f8a2f05db04c"
    )
    assert set(manifest["committed_summaries"]) == SUMMARY_FILES
    assert {path.name for path in EVIDENCE.iterdir()} == SUMMARY_FILES | {"manifest.json"}

    for name, expected_digest in manifest["committed_summaries"].items():
        digest = hashlib.sha256((EVIDENCE / name).read_bytes()).hexdigest()
        assert digest == expected_digest


def test_glue_probe_proves_definition_access_without_workload_execution() -> None:
    probe = load("glue-service-probe.json")
    cleanup = load("cleanup-verification.json")

    assert probe["status"] == "GLUE_CREATE_JOB_VERIFIED"
    assert probe["account"] == "857229544428"
    assert probe["region"] == "ap-southeast-2"
    assert probe["run_id"] == "32930567869"
    assert probe["source_commit"] == "bca352732cb9e5d82627edc32321003ad5e0676e"
    assert probe["glue_job_name"] == "atlasretail-probe-32930567869"
    assert probe["iam_role_name"] == "atlasretail-probe-32930567869-glue"
    assert probe["glue_job_runs"] == 0
    assert probe["workload_started"] is False
    assert probe["cleanup"] == {
        "glue_job": "DELETED_AND_VERIFIED",
        "iam_role": "DELETED_AND_VERIFIED",
    }
    assert probe["errors"] == []

    assert cleanup["result"] == "PASS"
    assert all(cleanup["checks"].values())
    assert cleanup["glue_job_lookup_result"] == "EntityNotFoundException"
    assert cleanup["iam_role_lookup_result"] == "NoSuchEntity"
    assert cleanup["errors"] == []
