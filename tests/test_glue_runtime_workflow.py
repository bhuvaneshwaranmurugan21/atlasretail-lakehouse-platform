from __future__ import annotations

from pathlib import Path

WORKFLOW = (Path(__file__).parents[1] / ".github" / "workflows" / "ci.yml").read_text(
    encoding="utf-8"
)
RUNTIME_JOB = WORKFLOW.split("  glue-runtime-integration:\n", maxsplit=1)[1].split(
    "\n  terraform:\n", maxsplit=1
)[0]


def test_runtime_matches_the_pinned_glue_5_versions() -> None:
    assert 'python-version: "3.11"' in RUNTIME_JOB
    assert "pyspark==3.5.4" in RUNTIME_JOB
    assert "iceberg-spark-runtime-3.5_2.12-1.7.1.jar" in RUNTIME_JOB
    assert "sha512sum --check --status" in RUNTIME_JOB


def test_runtime_integration_never_requests_aws_credentials() -> None:
    assert "AWS_EC2_METADATA_DISABLED=true" in RUNTIME_JOB
    assert "configure-aws-credentials" not in RUNTIME_JOB
    assert "role-to-assume" not in RUNTIME_JOB
    assert "aws glue" not in RUNTIME_JOB
