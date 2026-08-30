"""Prove Atlas has no deployment state, live lease, or unexpected AWS resources."""

from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any


def command(*arguments: str) -> tuple[int, str]:
    completed = subprocess.run(arguments, check=False, capture_output=True, text=True)
    return completed.returncode, completed.stdout + completed.stderr


def _json(code: int, detail: str) -> dict[str, Any] | None:
    if code != 0:
        return None
    try:
        parsed = json.loads(detail)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def _resources(module: dict[str, Any]) -> list[str]:
    addresses = [
        str(item.get("address", "unknown"))
        for item in module.get("resources", [])
        if isinstance(item, dict)
    ]
    for child in module.get("child_modules", []):
        if isinstance(child, dict):
            addresses.extend(_resources(child))
    return addresses


def _alias_names(document: dict[str, Any]) -> list[str] | None:
    aliases = document.get("Aliases")
    if not isinstance(aliases, list):
        return None
    names: list[str] = []
    for alias in aliases:
        if not isinstance(alias, dict) or not isinstance(alias.get("AliasName"), str):
            return None
        names.append(alias["AliasName"])
    return sorted(names)


def verify(
    terraform_directory: str,
    account_lease_table: str,
    expected_lease_owner: str | None = None,
    *,
    allow_expected_lease_absent: bool = False,
) -> dict[str, Any]:
    errors: list[str] = []
    state_code, state_detail = command(
        "terraform", f"-chdir={terraform_directory}", "show", "-json"
    )
    state = _json(state_code, state_detail)
    if state is None:
        errors.append("Terraform state is unreadable")
        remaining_state: list[str] = []
    else:
        root = state.get("values", {}).get("root_module", {})
        remaining_state = _resources(root) if isinstance(root, dict) else []
        if remaining_state:
            errors.append("Terraform state is not empty")

    lease_code, lease_detail = command(
        "aws",
        "dynamodb",
        "get-item",
        "--table-name",
        account_lease_table,
        "--key",
        '{"lock_id":{"S":"portfolio-lab"}}',
        "--consistent-read",
        "--output",
        "json",
    )
    lease_document = _json(lease_code, lease_detail)
    lease_absent = False
    lease_item: dict[str, Any] | None = None
    lease_owner: str | None = None
    lease_expires_at: int | None = None
    lease_ownership_verified = False
    if lease_code != 0:
        errors.append("Account-wide lease is unreadable")
    elif not lease_detail.strip():
        # The AWS CLI emits no JSON document for a successful GetItem miss.
        lease_absent = True
    elif lease_document is None:
        errors.append("Account-wide lease response is malformed")
    elif "Item" not in lease_document:
        lease_absent = True
    elif isinstance(lease_document["Item"], dict) and lease_document["Item"]:
        lease_item = lease_document["Item"]
        owner_value = lease_item.get("owner")
        expiry_value = lease_item.get("expires_at")
        lock_value = lease_item.get("lock_id")
        lease_owner = owner_value.get("S") if isinstance(owner_value, dict) else None
        expiry_text = expiry_value.get("N") if isinstance(expiry_value, dict) else None
        lock_id = lock_value.get("S") if isinstance(lock_value, dict) else None
        try:
            lease_expires_at = int(expiry_text) if isinstance(expiry_text, str) else None
        except ValueError:
            lease_expires_at = None
        if expected_lease_owner is None:
            errors.append("Account-wide lease is still held")
        elif (
            lock_id == "portfolio-lab"
            and lease_owner == expected_lease_owner
            and lease_expires_at is not None
            and lease_expires_at > int(time.time())
        ):
            lease_ownership_verified = True
        else:
            errors.append("Account-wide lease does not match the expected live owner")
    else:
        errors.append("Account-wide lease response is malformed")

    if expected_lease_owner is not None and lease_absent and not allow_expected_lease_absent:
        errors.append("Expected account-wide lease is absent")

    tag_code, tag_detail = command(
        "aws",
        "resourcegroupstaggingapi",
        "get-resources",
        "--tag-filters",
        "Key=Project,Values=AtlasRetail",
        "--output",
        "json",
    )
    inventory = _json(tag_code, tag_detail)
    unexpected: list[str] = []
    allowed_pending_kms: list[str] = []
    pending_kms_aliases: dict[str, list[str]] = {}
    kms_inspection_errors: list[str] = []
    if inventory is None:
        errors.append("AtlasRetail tag inventory is unreadable")
    else:
        arns = sorted(
            str(item["ResourceARN"])
            for item in inventory.get("ResourceTagMappingList", [])
            if isinstance(item, dict) and item.get("ResourceARN")
        )
        for arn in arns:
            if ":kms:" not in arn:
                unexpected.append(arn)
                continue
            key_code, key_detail = command(
                "aws", "kms", "describe-key", "--key-id", arn, "--output", "json"
            )
            key = _json(key_code, key_detail)
            metadata = key.get("KeyMetadata", {}) if key else {}
            if (
                isinstance(metadata, dict)
                and metadata.get("KeyState") == "PendingDeletion"
                and metadata.get("DeletionDate")
            ):
                alias_code, alias_detail = command(
                    "aws",
                    "kms",
                    "list-aliases",
                    "--key-id",
                    arn,
                    "--output",
                    "json",
                )
                alias_document = _json(alias_code, alias_detail)
                alias_names = _alias_names(alias_document) if alias_document else None
                if alias_names is None:
                    kms_inspection_errors.append(f"{arn}: aliases are unreadable")
                    unexpected.append(arn)
                else:
                    pending_kms_aliases[arn] = alias_names
                    if alias_names:
                        kms_inspection_errors.append(f"{arn}: aliases remain attached")
                        unexpected.append(arn)
                    else:
                        allowed_pending_kms.append(arn)
            else:
                if key is None:
                    kms_inspection_errors.append(f"{arn}: key metadata is unreadable")
                else:
                    kms_inspection_errors.append(
                        f"{arn}: key is not a verifiable pending-deletion exception"
                    )
                unexpected.append(arn)
        if unexpected:
            errors.append("Unexpected live AtlasRetail resources exist")

    return {
        "result": "PASS" if not errors else "FAIL",
        "terraform_state_resources": remaining_state,
        "account_lease_table": account_lease_table,
        "account_lease_read_exit_code": lease_code,
        "account_lease_absent": lease_absent,
        "account_lease_item": lease_item,
        "account_lease_expected_owner": expected_lease_owner,
        "account_lease_owner": lease_owner,
        "account_lease_expires_at": lease_expires_at,
        "account_lease_ownership_verified": lease_ownership_verified,
        "account_lease_absence_allowed": allow_expected_lease_absent,
        "allowed_pending_deletion_kms_keys": allowed_pending_kms,
        "pending_deletion_kms_aliases": pending_kms_aliases,
        "kms_inspection_errors": kms_inspection_errors,
        "unexpected_resources": unexpected,
        "errors": errors,
    }


def main(arguments: list[str]) -> int:
    if len(arguments) not in {4, 5, 6}:
        print(
            "usage: verify_preflight.py TF_DIR OUTPUT_JSON ACCOUNT_LEASE_TABLE "
            "[EXPECTED_LEASE_OWNER [ALLOW_ABSENT]]",
            file=sys.stderr,
        )
        return 2
    expected_owner = arguments[4] if len(arguments) == 5 else None
    allow_absent = False
    if len(arguments) == 6:
        expected_owner = arguments[4]
        if arguments[5] != "ALLOW_ABSENT":
            print("sixth argument must be ALLOW_ABSENT", file=sys.stderr)
            return 2
        allow_absent = True
    result = verify(
        arguments[1],
        arguments[3],
        expected_owner,
        allow_expected_lease_absent=allow_absent,
    )
    output = Path(arguments[2])
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return 0 if result["result"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
