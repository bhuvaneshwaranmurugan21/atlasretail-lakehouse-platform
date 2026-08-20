"""Build the immutable AtlasRetail plan-only evidence summary and digest manifest."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Any


def load(root: Path, name: str) -> dict[str, Any]:
    value = json.loads((root / name).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{name} is not a JSON object")
    return value


def main(arguments: list[str]) -> int:
    if len(arguments) != 4:
        print(
            "usage: summarize_plan_evidence.py EVIDENCE_DIR SOURCE_COMMIT RUN_ID",
            file=sys.stderr,
        )
        return 2
    root = Path(arguments[1])
    source_commit = arguments[2]
    run_id = arguments[3]
    checks = {
        "account_plan": load(root, "account-plan-verification.json").get("result") == "PASS",
        "budget": load(root, "budget-verification.json").get("result") == "PASS",
        "iam_parity": load(root, "iam-parity.json").get("result") == "PASS",
        "pre_plan_baseline": load(root, "preflight-before.json").get("result") == "PASS",
        "terraform_plan": load(root, "terraform-plan-validation.json").get("result") == "PASS",
        "state_machine": load(root, "state-machine-validation.json").get("result") == "OK",
        "zero_persistent_change": load(root, "no-change-verification.json").get("result") == "PASS",
    }
    budget = load(root, "budget-verification.json")
    plan = load(root, "terraform-plan-validation.json")
    result = "PASS" if all(checks.values()) else "FAIL"
    summary = {
        "project": "atlasretail-lakehouse-platform",
        "claim_level": "AWS_PLAN_VERIFIED" if result == "PASS" else "AWS_PLAN_INCOMPLETE",
        "production_claim": False,
        "source_commit": source_commit,
        "github_run_id": run_id,
        "result": result,
        "checks": checks,
        "infrastructure_deployed": False,
        "saved_plan_applied": False,
        "planned_managed_resource_count": plan.get("resource_count"),
        "planned_resource_type_counts": plan.get("resource_type_counts"),
        "cost_control": {
            "planned_gross_cost_ceiling_usd": budget.get("planned_gross_cost_ceiling_usd"),
            "budget_headroom_usd": budget.get("budget_headroom_usd"),
            "remaining_account_credit_usd": load(root, "account-plan-verification.json").get(
                "remaining_credit_usd"
            ),
            "measured_workload_cost": False,
        },
        "warnings": budget.get("warnings", []),
    }
    (root / "summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    hashes = {}
    for path in sorted(root.rglob("*")):
        if path.is_file() and path.name != "manifest-sha256.json":
            hashes[str(path.relative_to(root))] = hashlib.sha256(path.read_bytes()).hexdigest()
    (root / "manifest-sha256.json").write_text(
        json.dumps(hashes, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return 0 if result == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
