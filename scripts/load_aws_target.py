#!/usr/bin/env python3
"""Validate and expose AtlasRetail's single checked-in AWS target."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TARGET = ROOT / ".github" / "atlas-target.json"

REQUIRED_STRINGS = {
    "schema_version",
    "project",
    "repository",
    "branch_ref",
    "aws_account_id",
    "aws_region",
    "oidc_role_name",
    "oidc_role_arn",
    "oidc_provider_arn",
    "terraform_state_bucket",
    "terraform_state_key",
    "terraform_lock_table",
    "account_lease_table",
    "budget_name",
}
REQUIRED_NUMBERS = {"monthly_budget_usd", "run_ceiling_usd"}
SOURCE_COMMIT_PATTERN = re.compile(r"^[0-9a-fA-F]{40}$")
GITHUB_RUN_ID_PATTERN = re.compile(r"^[1-9][0-9]*$")


def load_target(path: Path = DEFAULT_TARGET) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("AWS target must be a JSON object")

    expected_keys = REQUIRED_STRINGS | REQUIRED_NUMBERS
    if set(value) != expected_keys:
        missing = sorted(expected_keys - set(value))
        extra = sorted(set(value) - expected_keys)
        raise ValueError(f"AWS target keys differ: missing={missing}, extra={extra}")

    for key in REQUIRED_STRINGS:
        if not isinstance(value[key], str) or not value[key]:
            raise ValueError(f"{key} must be a non-empty string")
        if "\n" in value[key] or "\r" in value[key]:
            raise ValueError(f"{key} must be a single-line value")
    for key in REQUIRED_NUMBERS:
        if not isinstance(value[key], int | float) or isinstance(value[key], bool):
            raise ValueError(f"{key} must be numeric")

    account = value["aws_account_id"]
    region = value["aws_region"]
    role_name = value["oidc_role_name"]
    if not re.fullmatch(r"\d{12}", account):
        raise ValueError("aws_account_id must contain exactly 12 digits")
    if not re.fullmatch(r"[a-z]{2}(?:-gov)?-[a-z]+-\d", region):
        raise ValueError("aws_region has an invalid format")
    if not re.fullmatch(r"[A-Za-z0-9+=,.@_-]{1,64}", role_name):
        raise ValueError("oidc_role_name has an invalid format")
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", value["repository"]):
        raise ValueError("repository must use owner/name format")
    if not value["branch_ref"].startswith("refs/heads/"):
        raise ValueError("branch_ref must be a complete branch ref")

    derived = {
        "oidc_role_arn": f"arn:aws:iam::{account}:role/{role_name}",
        "oidc_provider_arn": (
            f"arn:aws:iam::{account}:oidc-provider/token.actions.githubusercontent.com"
        ),
        "terraform_state_bucket": f"portfolio-lab-tfstate-{account}-{region}",
    }
    for key, expected in derived.items():
        if value[key] != expected:
            raise ValueError(f"{key} must equal its derived value {expected!r}")

    if value["project"] != "AtlasRetail" or value["schema_version"] != "1.0":
        raise ValueError("unsupported project or target schema version")
    if value["run_ceiling_usd"] <= 0:
        raise ValueError("run_ceiling_usd must be positive")
    if value["monthly_budget_usd"] < value["run_ceiling_usd"]:
        raise ValueError("monthly budget must cover the per-run ceiling")
    return value


def _append_values(path: Path, values: dict[str, Any], *, upper: bool) -> None:
    with path.open("a", encoding="utf-8") as handle:
        for key in sorted(values):
            output_key = key.upper() if upper else key
            handle.write(f"{output_key}={values[key]}\n")


def _assert_equal(label: str, actual: str | None, expected: str) -> None:
    if actual is not None and actual != expected:
        raise ValueError(f"{label} mismatch")


def build_source_identity(
    target: dict[str, Any], source_commit: str, github_run_id: str
) -> dict[str, Any]:
    if SOURCE_COMMIT_PATTERN.fullmatch(source_commit) is None:
        raise ValueError("source commit must contain exactly 40 hexadecimal characters")
    if GITHUB_RUN_ID_PATTERN.fullmatch(github_run_id) is None:
        raise ValueError("GitHub run ID must be a positive integer")
    return {
        "schema_version": "1.0",
        "project": target["project"],
        "result": "PASS",
        "source_commit": source_commit,
        "github_run_id": github_run_id,
        "repository": target["repository"],
        "ref": target["branch_ref"],
        "aws_account_id": target["aws_account_id"],
        "aws_region": target["aws_region"],
        "oidc_role_arn": target["oidc_role_arn"],
        "terraform_state_key": target["terraform_state_key"],
        "run_ceiling_usd": target["run_ceiling_usd"],
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--target", type=Path, default=DEFAULT_TARGET)
    parser.add_argument("--github-output", type=Path)
    parser.add_argument("--github-env", type=Path)
    parser.add_argument("--expect-account")
    parser.add_argument("--expect-region")
    parser.add_argument("--expect-role-arn")
    parser.add_argument("--expect-repository")
    parser.add_argument("--expect-ref")
    parser.add_argument("--source-identity", type=Path)
    parser.add_argument("--source-commit")
    parser.add_argument("--github-run-id")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    target = load_target(args.target)
    _assert_equal("account", args.expect_account, target["aws_account_id"])
    _assert_equal("region", args.expect_region, target["aws_region"])
    _assert_equal("role ARN", args.expect_role_arn, target["oidc_role_arn"])
    _assert_equal("repository", args.expect_repository, target["repository"])
    _assert_equal("ref", args.expect_ref, target["branch_ref"])
    source_arguments = (args.source_identity, args.source_commit, args.github_run_id)
    if any(value is not None for value in source_arguments):
        if not all(value is not None for value in source_arguments):
            raise ValueError(
                "source identity output, source commit, and GitHub run ID are all required"
            )
        identity = build_source_identity(target, args.source_commit, args.github_run_id)
        args.source_identity.parent.mkdir(parents=True, exist_ok=True)
        args.source_identity.write_text(
            json.dumps(identity, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
    if args.github_output:
        _append_values(args.github_output, target, upper=False)
    if args.github_env:
        _append_values(args.github_env, target, upper=True)
    if not args.github_output and not args.github_env and not args.source_identity:
        print(json.dumps(target, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
