"""Verify Terraform state is empty and named ephemeral resources are gone."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any


def command(*arguments: str) -> tuple[int, str]:
    completed = subprocess.run(arguments, check=False, capture_output=True, text=True)
    return completed.returncode, completed.stdout + completed.stderr


outputs: dict[str, Any] = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
checks: list[dict[str, Any]] = []
for output_name in ("landing_bucket", "warehouse_bucket", "evidence_bucket"):
    name = outputs[output_name]["value"]
    code, detail = command("aws", "s3api", "head-bucket", "--bucket", name)
    checks.append({"resource": name, "deleted": code != 0, "detail": detail[-500:]})

commands = [
    ("control_table", "aws", "dynamodb", "describe-table", "--table-name"),
    ("glue_job_name", "aws", "glue", "get-job", "--job-name"),
    ("state_machine_arn", "aws", "stepfunctions", "describe-state-machine", "--state-machine-arn"),
]
for output_name, *prefix in commands:
    name = outputs[output_name]["value"]
    code, detail = command(*prefix, name)
    checks.append({"resource": name, "deleted": code != 0, "detail": detail[-500:]})

state_code, state_json = command("terraform", f"-chdir={sys.argv[2]}", "show", "-json")
state = json.loads(state_json) if state_code == 0 and state_json.strip() else {}
root_module = state.get("values", {}).get("root_module", {})
state_empty = not root_module.get("resources") and not root_module.get("child_modules")
checks.append(
    {"resource": "terraform-state", "deleted": state_empty, "detail": "empty after destroy"}
)

result = {
    "result": "PASS" if all(check["deleted"] for check in checks) else "FAIL",
    "checks": checks,
    "kms_note": "The KMS key is scheduled for deletion after the mandatory seven-day AWS window.",
}
Path(sys.argv[3]).write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
raise SystemExit(0 if result["result"] == "PASS" else 1)
