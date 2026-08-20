"""Build the sanitized final summary for an AtlasRetail deployment canary."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Any


def read_json(path: Path) -> dict[str, Any]:
    try:
        parsed = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def summarize(evidence_directory: Path, source_commit: str, run_id: str) -> dict[str, Any]:
    deployment = read_json(evidence_directory / "deployment-verification.json")
    teardown = read_json(evidence_directory / "teardown.json")
    apply_plan = read_json(evidence_directory / "terraform-apply-plan-validation.json")
    destroy_plan = read_json(evidence_directory / "terraform-destroy-plan-validation.json")
    deployment_passed = deployment.get("result") == "PASS"
    teardown_passed = teardown.get("result") == "PASS"
    plans_passed = apply_plan.get("result") == "PASS" and destroy_plan.get("result") == "PASS"
    passed = deployment_passed and teardown_passed and plans_passed
    return {
        "schema_version": "1.0",
        "project": "AtlasRetail",
        "part": "controlled-deployment",
        "source_commit": source_commit,
        "github_run_id": run_id,
        "result": "PASS" if passed else "FAIL",
        "claim": "AWS_DEPLOYMENT_VERIFIED" if passed else "NONE",
        "deployment": "PASS" if deployment_passed else "FAIL",
        "readiness": deployment.get("result", "MISSING"),
        "zero_workload": deployment.get("zero_workload", "MISSING"),
        "apply_plan": apply_plan.get("result", "MISSING"),
        "destroy_plan": destroy_plan.get("result", "MISSING"),
        "teardown": teardown.get("result", "MISSING"),
        "active_residue": 0 if teardown_passed else "UNKNOWN",
        "terraform_managed_resource_count": deployment.get("terraform_managed_resource_count", 0),
    }


def write_manifest(evidence_directory: Path) -> None:
    entries: list[str] = []
    for path in sorted(evidence_directory.iterdir()):
        if not path.is_file() or path.name in {
            "evidence-manifest.sha256",
            "terraform-apply-plan.json",
            "terraform-apply-plan.txt",
            "terraform-destroy-plan.json",
            "terraform-destroy-plan.txt",
            "terraform-outputs.json",
        }:
            continue
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        entries.append(f"{digest}  {path.name}")
    (evidence_directory / "evidence-manifest.sha256").write_text(
        "\n".join(entries) + "\n", encoding="utf-8"
    )


def main(arguments: list[str]) -> int:
    if len(arguments) != 4:
        print(
            "usage: summarize_deployment_evidence.py EVIDENCE_DIR SOURCE_COMMIT RUN_ID",
            file=sys.stderr,
        )
        return 2
    evidence_directory = Path(arguments[1])
    evidence_directory.mkdir(parents=True, exist_ok=True)
    summary = summarize(evidence_directory, arguments[2], arguments[3])
    (evidence_directory / "part-2-summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    write_manifest(evidence_directory)
    return 0 if summary["result"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
