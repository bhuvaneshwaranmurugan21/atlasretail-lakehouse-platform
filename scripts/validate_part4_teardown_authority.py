#!/usr/bin/env python3
"""Independently validate immutable Part 4 teardown authority."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from terraform_source_digest import source_digest

from atlasretail.part4_contract import (
    CONTRACT_RELATIVE_PATH,
    TARGET_RELATIVE_PATH,
    load_json_object,
    validate_part4_contract_file,
)
from atlasretail.part4_teardown_authority import (
    AuthorityContext,
    AuthorityError,
    AuthorityInputs,
    load_object,
    sha256_path,
    validate_authority,
)


def arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository-root", type=Path, default=Path("."))
    parser.add_argument("--authority", type=Path, required=True)
    parser.add_argument("--digest-receipt", type=Path, required=True)
    parser.add_argument("--admission-receipt", type=Path, required=True)
    parser.add_argument("--apply-plan-json", type=Path)
    parser.add_argument("--apply-plan-binary", type=Path)
    parser.add_argument("--allow-authority-bound-plan-digests", action="store_true")
    parser.add_argument("--apply-plan-validation", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--repository-owner", required=True)
    parser.add_argument("--workflow-name", required=True)
    parser.add_argument("--event", required=True)
    parser.add_argument("--ref", required=True)
    parser.add_argument("--actor", required=True)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--run-attempt", required=True)
    parser.add_argument("--order-count", type=int, required=True)
    parser.add_argument("--budget-ceiling-usd", type=int, required=True)
    parser.add_argument("--account-id", required=True)
    parser.add_argument("--region", required=True)
    parser.add_argument("--oidc-role-arn", required=True)
    parser.add_argument("--backend-bucket", required=True)
    parser.add_argument("--backend-key", required=True)
    parser.add_argument("--terraform-lock-table", required=True)
    parser.add_argument("--lease-table", required=True)
    parser.add_argument("--lease-owner", required=True)
    parser.add_argument("--terraform-version", required=True)
    return parser.parse_args()


def main() -> int:
    args = arguments()
    try:
        root = args.repository_root.resolve()
        contract_path = root / CONTRACT_RELATIVE_PATH
        contract_validation = validate_part4_contract_file(contract_path, repo_root=root)
        contract = load_json_object(contract_path)
        authority = load_object(args.authority)
        digest = load_object(args.digest_receipt)
        admission = load_object(args.admission_receipt)
        plan_validation = load_object(args.apply_plan_validation)
        context = AuthorityContext(
            repository=args.repository,
            repository_owner=args.repository_owner,
            workflow_name=args.workflow_name,
            event=args.event,
            ref=args.ref,
            actor=args.actor,
            source_commit=args.source_commit,
            run_id=args.run_id,
            run_attempt=args.run_attempt,
            order_count=args.order_count,
            budget_ceiling_usd=args.budget_ceiling_usd,
            account_id=args.account_id,
            region=args.region,
            oidc_role_arn=args.oidc_role_arn,
            backend_bucket=args.backend_bucket,
            backend_key=args.backend_key,
            terraform_lock_table=args.terraform_lock_table,
            lease_table=args.lease_table,
            lease_owner=args.lease_owner,
            terraform_version=args.terraform_version,
        )
        terraform_values = authority.get("terraform")
        if not isinstance(terraform_values, dict):
            raise AuthorityError("authority Terraform bindings are absent")
        both_plan_files = bool(args.apply_plan_json and args.apply_plan_binary)
        if bool(args.apply_plan_json) != bool(args.apply_plan_binary):
            raise AuthorityError("apply plan JSON and binary must be supplied together")
        if not both_plan_files and not args.allow_authority_bound_plan_digests:
            raise AuthorityError("original apply plan files are required outside recovery")
        plan_json_sha = (
            sha256_path(args.apply_plan_json)
            if args.apply_plan_json
            else str(terraform_values.get("apply_plan_json_sha256", ""))
        )
        plan_binary_sha = (
            sha256_path(args.apply_plan_binary)
            if args.apply_plan_binary
            else str(terraform_values.get("apply_plan_binary_sha256", ""))
        )
        inputs = AuthorityInputs(
            contract_id=contract["contract_id"],
            contract_version=contract["version"],
            contract_sha256=contract_validation.contract_sha256,
            target_sha256=sha256_path(root / TARGET_RELATIVE_PATH),
            authority_schema_sha256=sha256_path(
                root / "contracts/part4/teardown-authority.schema.json"
            ),
            admission_receipt_sha256=sha256_path(args.admission_receipt),
            source_tree_sha256=str(admission.get("sources", {}).get("source_tree_sha256", "")),
            source_provenance_summary_sha256=str(
                admission.get("sources", {}).get("source_provenance_summary_sha256", "")
            ),
            provider_lock_sha256=sha256_path(root / "infra/atlas/.terraform.lock.hcl"),
            infrastructure_digest=source_digest(root),
            apply_plan_json_sha256=plan_json_sha,
            apply_plan_binary_sha256=plan_binary_sha,
            apply_plan_validation_sha256=sha256_path(args.apply_plan_validation),
        )
        proof = validate_authority(authority, context, inputs, admission, plan_validation)
        if digest != {
            "schema_version": "1.0",
            "proof": "part4-teardown-authority-digest",
            "result": "PASS",
            "authority_file": args.authority.name,
            "authority_sha256": sha256_path(args.authority),
            "run_id": context.run_id,
            "run_attempt": context.run_attempt,
            "lease_owner": context.lease_owner,
        }:
            raise AuthorityError("authority digest receipt differs from exact authority bytes")
        proof["authority_file_sha256"] = sha256_path(args.authority)
        proof["plan_files_revalidated"] = both_plan_files
        proof["authority_bound_recovery_mode"] = not both_plan_files
    except (AuthorityError, OSError, ValueError) as error:
        proof = {
            "schema_version": "1.0",
            "proof": "part4-teardown-authority-verification",
            "result": "FAIL",
            "claim_level": "UNCLAIMED",
            "aws_execution": False,
            "errors": [str(error)],
        }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(proof, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if proof["result"] != "PASS":
        print(json.dumps(proof, indent=2, sort_keys=True), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
