from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).parents[1]
GLUE = (ROOT / "aws" / "glue" / "atlasretail_iceberg.py").read_text(encoding="utf-8")
TERRAFORM = (ROOT / "infra" / "atlas" / "main.tf").read_text(encoding="utf-8")


def test_glue_reads_registered_versions_and_rejects_object_drift() -> None:
    assert 'VersionId=args["MANIFEST_VERSION_ID"]' in GLUE
    assert "VersionId=version_id" in GLUE
    assert 'ChecksumMode="ENABLED"' in GLUE
    assert 'fail("OBJECT_IDENTITY"' in GLUE
    assert "CopySourceIfMatch" in GLUE


def test_glue_enforces_exactly_one_temporal_match_and_records_snapshots() -> None:
    assert 'F.col("dimension_matches") == 0' in GLUE
    assert 'F.col("dimension_matches") > 1' in GLUE
    assert 'fail("AMBIGUOUS_DIMENSION"' in GLUE
    assert "snapshot_id" in GLUE
    assert 'args["VALIDATION_URI"]' in GLUE


def test_state_machine_uses_registration_identity_and_failure_handlers() -> None:
    assert '"--GENERATION_ID.$"' in TERRAFORM
    assert '"$.registration.result.generation_id"' in TERRAFORM
    assert '"MarkGlueFailure"' in TERRAFORM
    assert "action" in TERRAFORM and '"validate"' in TERRAFORM
    assert "failure_stage" in TERRAFORM and '"PUBLICATION"' in TERRAFORM


def test_state_machine_waits_for_execution_role_policy() -> None:
    resource = TERRAFORM.split('resource "aws_sfn_state_machine" "retail" {', maxsplit=1)[1].split(
        "\n}", maxsplit=1
    )[0]
    assert "depends_on = [aws_iam_role_policy.states]" in resource
