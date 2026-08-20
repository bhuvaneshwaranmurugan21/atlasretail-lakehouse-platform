from __future__ import annotations

import importlib.util
import json
from pathlib import Path

SCRIPT = Path(__file__).parents[1] / "scripts" / "summarize_deployment_evidence.py"
SPEC = importlib.util.spec_from_file_location("summarize_deployment_evidence", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def write_json(path: Path, value: dict[str, object]) -> None:
    path.write_text(json.dumps(value), encoding="utf-8")


def test_summary_requires_deployment_plans_and_teardown(tmp_path: Path) -> None:
    write_json(
        tmp_path / "deployment-verification.json",
        {"result": "PASS", "zero_workload": "PASS", "terraform_managed_resource_count": 40},
    )
    write_json(tmp_path / "teardown.json", {"result": "PASS"})
    write_json(tmp_path / "terraform-apply-plan-validation.json", {"result": "PASS"})
    write_json(tmp_path / "terraform-destroy-plan-validation.json", {"result": "PASS"})

    result = MODULE.summarize(tmp_path, "a" * 40, "123")

    assert result["result"] == "PASS"
    assert result["claim"] == "AWS_DEPLOYMENT_VERIFIED"
    assert result["active_residue"] == 0


def test_summary_rejects_success_when_teardown_is_missing(tmp_path: Path) -> None:
    write_json(tmp_path / "deployment-verification.json", {"result": "PASS"})
    write_json(tmp_path / "terraform-apply-plan-validation.json", {"result": "PASS"})
    write_json(tmp_path / "terraform-destroy-plan-validation.json", {"result": "PASS"})

    result = MODULE.summarize(tmp_path, "a" * 40, "123")

    assert result["result"] == "FAIL"
    assert result["claim"] == "NONE"
    assert result["active_residue"] == "UNKNOWN"


def test_manifest_excludes_raw_terraform_material(tmp_path: Path) -> None:
    (tmp_path / "part-2-summary.json").write_text("{}", encoding="utf-8")
    (tmp_path / "terraform-apply-plan.json").write_text("private", encoding="utf-8")
    (tmp_path / "terraform-outputs.json").write_text("private", encoding="utf-8")

    MODULE.write_manifest(tmp_path)

    manifest = (tmp_path / "evidence-manifest.sha256").read_text(encoding="utf-8")
    assert "part-2-summary.json" in manifest
    assert "terraform-apply-plan.json" not in manifest
    assert "terraform-outputs.json" not in manifest
