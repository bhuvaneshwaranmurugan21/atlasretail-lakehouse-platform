"""Fail closed unless Terraform state and AWS inventories prove teardown."""

from __future__ import annotations

import json
import subprocess
import sys
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any

Runner = Callable[..., tuple[int, str]]


def command(*arguments: str) -> tuple[int, str]:
    """Run a command without raising so every cleanup check reaches the report."""
    completed = subprocess.run(arguments, check=False, capture_output=True, text=True)
    return completed.returncode, completed.stdout + completed.stderr


def output_value(outputs: dict[str, Any], name: str) -> str:
    """Read a required string from Terraform's output JSON."""
    value = outputs.get(name, {}).get("value")
    if not isinstance(value, str) or not value:
        raise ValueError(f"Terraform output {name!r} is missing or is not a string")
    return value


def confirmed_absent(code: int, detail: str, markers: Iterable[str]) -> bool:
    """Accept only an explicit service-specific not-found response."""
    normalized = detail.lower()
    return code != 0 and any(marker.lower() in normalized for marker in markers)


def verify(
    outputs: dict[str, Any],
    terraform_directory: str,
    run_id: str,
    runner: Runner = command,
) -> dict[str, Any]:
    """Verify named resources, Terraform state, and the run-wide tag inventory."""
    checks: list[dict[str, Any]] = []

    for output_name in ("landing_bucket", "warehouse_bucket", "evidence_bucket"):
        try:
            name = output_value(outputs, output_name)
        except ValueError as error:
            checks.append({"resource": output_name, "deleted": False, "detail": str(error)})
            continue
        code, detail = runner("aws", "s3api", "head-bucket", "--bucket", name)
        checks.append(
            {
                "resource": name,
                "deleted": confirmed_absent(code, detail, ("404", "not found", "nosuchbucket")),
                "detail": detail[-500:],
            }
        )

    named_checks = (
        (
            "control_table",
            ("aws", "dynamodb", "describe-table", "--table-name"),
            ("ResourceNotFoundException",),
        ),
        (
            "glue_job_name",
            ("aws", "glue", "get-job", "--job-name"),
            ("EntityNotFoundException",),
        ),
        (
            "state_machine_arn",
            (
                "aws",
                "stepfunctions",
                "describe-state-machine",
                "--state-machine-arn",
            ),
            ("StateMachineDoesNotExist",),
        ),
    )
    for output_name, prefix, markers in named_checks:
        try:
            name = output_value(outputs, output_name)
        except ValueError as error:
            checks.append({"resource": output_name, "deleted": False, "detail": str(error)})
            continue
        code, detail = runner(*prefix, name)
        checks.append(
            {
                "resource": name,
                "deleted": confirmed_absent(code, detail, markers),
                "detail": detail[-500:],
            }
        )

    state_code, state_json = runner("terraform", f"-chdir={terraform_directory}", "show", "-json")
    state_empty = False
    state_detail = state_json[-500:]
    if state_code == 0 and state_json.strip():
        try:
            state = json.loads(state_json)
            root_module = state.get("values", {}).get("root_module", {})
            state_empty = not root_module.get("resources") and not root_module.get("child_modules")
            state_detail = "Terraform state is readable and empty."
        except (json.JSONDecodeError, AttributeError):
            state_detail = "Terraform state output is not valid JSON."
    elif state_code != 0:
        state_detail = f"Terraform state is unreadable: {state_detail}"
    else:
        state_detail = "Terraform returned no state JSON."
    checks.append(
        {
            "resource": "terraform-state",
            "deleted": state_empty,
            "detail": state_detail,
        }
    )

    tag_code, tag_json = runner(
        "aws",
        "resourcegroupstaggingapi",
        "get-resources",
        "--tag-filters",
        f"Key=RunId,Values={run_id}",
        "--output",
        "json",
    )
    inventory_clean = False
    inventory_detail = tag_json[-500:]
    if tag_code == 0 and tag_json.strip():
        try:
            mappings = json.loads(tag_json).get("ResourceTagMappingList", [])
            remaining = {
                mapping.get("ResourceARN")
                for mapping in mappings
                if isinstance(mapping, dict) and mapping.get("ResourceARN")
            }
            kms_key_arn = output_value(outputs, "kms_key_arn")
            allowed = {kms_key_arn}
            unexpected = sorted(remaining - allowed)
            inventory_clean = not unexpected
            inventory_detail = json.dumps(
                {
                    "allowed_scheduled_kms_keys": sorted(remaining & allowed),
                    "unexpected_resources": unexpected,
                },
                sort_keys=True,
            )
        except ValueError as error:
            inventory_detail = str(error)
        except (json.JSONDecodeError, AttributeError, TypeError):
            inventory_detail = "RunId tag inventory is not valid JSON."
    elif tag_code != 0:
        inventory_detail = f"RunId tag inventory is unreadable: {inventory_detail}"
    else:
        inventory_detail = "AWS returned no RunId tag inventory JSON."
    checks.append(
        {
            "resource": f"RunId={run_id} tag inventory",
            "deleted": inventory_clean,
            "detail": inventory_detail,
        }
    )

    return {
        "result": "PASS" if all(check["deleted"] for check in checks) else "FAIL",
        "checks": checks,
        "kms_note": (
            "A RunId-tagged KMS key may remain only while AWS completes its mandatory "
            "scheduled-deletion window."
        ),
    }


def main(arguments: list[str]) -> int:
    """Write machine-readable teardown evidence and return its status."""
    if len(arguments) != 5:
        print(
            "usage: verify_teardown.py OUTPUTS_JSON TF_DIR RUN_ID EVIDENCE_JSON",
            file=sys.stderr,
        )
        return 2
    try:
        parsed_outputs = json.loads(Path(arguments[1]).read_text(encoding="utf-8"))
        outputs = parsed_outputs if isinstance(parsed_outputs, dict) else {}
    except (OSError, json.JSONDecodeError):
        outputs = {}
    result = verify(outputs, arguments[2], arguments[3])
    evidence_path = Path(arguments[4])
    evidence_path.parent.mkdir(parents=True, exist_ok=True)
    evidence_path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return 0 if result["result"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
