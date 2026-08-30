from pathlib import Path

ROOT = Path(__file__).parents[1]
BOUNDED = (ROOT / ".github/workflows/aws-bounded-lab.yml").read_text(encoding="utf-8")
CI = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")


def test_bounded_workflow_consumes_only_validated_catalog_sources() -> None:
    assert "atlasretail generate-sources" in BOUNDED
    assert '--source-commit "${GITHUB_SHA}"' in BOUNDED
    assert 'python scripts/validate_part4_sources.py --directory "${source_root}"' in BOUNDED
    assert "source-provenance-summary.json" in BOUNDED
    assert "tamper-mutation.json" in BOUNDED
    assert "tamper-replacement.bin" in BOUNDED
    assert ".artifacts/aws" not in BOUNDED
    assert "success:21:none" not in BOUNDED
    assert "python -m atlasretail.cli generate" not in BOUNDED


def test_ci_independently_reproduces_and_retains_stage2_evidence() -> None:
    assert "python scripts/validate_part4_sources.py" in CI
    assert CI.count("atlasretail generate-sources") == 2
    assert 'diff -ru "${first}" "${second}"' in CI
    assert "part4-stage2-source-provenance-${{ github.run_id }}" in CI
    assert "tamper/tamper-mutation.json" in CI
