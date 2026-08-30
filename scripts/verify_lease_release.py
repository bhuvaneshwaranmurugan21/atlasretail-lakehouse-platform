#!/usr/bin/env python3
"""Delete the exact owned account lease and prove consistent-read absence."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--table", required=True)
    parser.add_argument("--owner", required=True)
    parser.add_argument("--region", required=True)
    parser.add_argument("--authority-sha256")
    parser.add_argument("--run-attempt")
    parser.add_argument("--source-commit")
    parser.add_argument("--contract-sha256")
    parser.add_argument("--target-sha256")
    parser.add_argument("--expected-state")
    parser.add_argument("--allow-absent", action="store_true")
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    key = '{"lock_id":{"S":"portfolio-lab"}}'
    expected = {":owner": {"S": arguments.owner}}
    conditions = ["#owner = :owner"]
    names = {"#owner": "owner"}
    if arguments.authority_sha256:
        expected[":authority"] = {"S": arguments.authority_sha256}
        conditions.append("authority_sha256 = :authority")
    if arguments.run_attempt:
        expected[":attempt"] = {"S": arguments.run_attempt}
        conditions.append("run_attempt = :attempt")
    if arguments.source_commit:
        expected[":source"] = {"S": arguments.source_commit}
        conditions.append("source_commit = :source")
    if arguments.contract_sha256:
        expected[":contract"] = {"S": arguments.contract_sha256}
        conditions.append("contract_sha256 = :contract")
    if arguments.target_sha256:
        expected[":target"] = {"S": arguments.target_sha256}
        conditions.append("target_sha256 = :target")
    if arguments.expected_state:
        expected[":state"] = {"S": arguments.expected_state}
        conditions.append("#state = :state")
        names["#state"] = "state"
    values = json.dumps(expected, separators=(",", ":"))
    common_result: dict[str, object] = {
        "owner": arguments.owner,
        "consistent_read": True,
        "authority_sha256": arguments.authority_sha256,
        "run_attempt": arguments.run_attempt,
        "source_commit": arguments.source_commit,
        "contract_sha256": arguments.contract_sha256,
        "target_sha256": arguments.target_sha256,
        "expected_state": arguments.expected_state,
        "allow_absent": arguments.allow_absent,
    }
    initial_item: object | None = None
    initial_read_exit_code: int | None = None
    if arguments.allow_absent:
        initial = subprocess.run(
            [
                "aws",
                "dynamodb",
                "get-item",
                "--region",
                arguments.region,
                "--table-name",
                arguments.table,
                "--key",
                key,
                "--consistent-read",
                "--output",
                "json",
                "--no-cli-pager",
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        initial_read_exit_code = initial.returncode
        initial_item = "UNREADABLE"
        if initial.returncode == 0:
            try:
                initial_payload = json.loads(initial.stdout or "{}")
            except json.JSONDecodeError:
                initial_payload = {"Item": "UNREADABLE"}
            initial_item = initial_payload.get("Item")
        if initial.returncode == 0 and initial_item is None:
            result = {
                **common_result,
                "result": "PASS",
                "lease_absent": True,
                "already_absent": True,
                "delete_attempted": False,
                "delete_exit_code": None,
                "initial_read_exit_code": initial.returncode,
                "initial_item": None,
                "post_delete_item": None,
            }
            arguments.output.parent.mkdir(parents=True, exist_ok=True)
            arguments.output.write_text(
                json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
            )
            return 0
        if initial.returncode != 0 or not isinstance(initial_item, dict) or not initial_item:
            result = {
                **common_result,
                "result": "FAIL",
                "lease_absent": False,
                "already_absent": False,
                "delete_attempted": False,
                "delete_exit_code": None,
                "initial_read_exit_code": initial.returncode,
                "initial_item": initial_item,
                "post_delete_item": None,
            }
            arguments.output.parent.mkdir(parents=True, exist_ok=True)
            arguments.output.write_text(
                json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
            )
            print("Lease state was not readable before guarded release", file=sys.stderr)
            return 1
    deleted = subprocess.run(
        [
            "aws",
            "dynamodb",
            "delete-item",
            "--region",
            arguments.region,
            "--table-name",
            arguments.table,
            "--key",
            key,
            "--condition-expression",
            " AND ".join(conditions),
            "--expression-attribute-names",
            json.dumps(names, separators=(",", ":")),
            "--expression-attribute-values",
            values,
            "--return-values",
            "ALL_OLD",
            "--output",
            "json",
            "--no-cli-pager",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    result: dict[str, object] = {
        **common_result,
        "result": "FAIL",
        "lease_absent": False,
        "already_absent": False,
        "delete_attempted": True,
        "delete_exit_code": deleted.returncode,
        "initial_read_exit_code": initial_read_exit_code,
        "initial_item": initial_item,
        "post_delete_item": None,
    }
    if deleted.returncode == 0:
        try:
            old = json.loads(deleted.stdout)
        except json.JSONDecodeError:
            old = {}
        removed_owner = old.get("Attributes", {}).get("owner", {}).get("S")
        removed_authority = old.get("Attributes", {}).get("authority_sha256", {}).get("S")
        removed_attempt = old.get("Attributes", {}).get("run_attempt", {}).get("S")
        removed_source = old.get("Attributes", {}).get("source_commit", {}).get("S")
        removed_contract = old.get("Attributes", {}).get("contract_sha256", {}).get("S")
        removed_target = old.get("Attributes", {}).get("target_sha256", {}).get("S")
        removed_state = old.get("Attributes", {}).get("state", {}).get("S")
        removed_matches = (
            removed_owner == arguments.owner
            and (
                arguments.authority_sha256 is None
                or removed_authority == arguments.authority_sha256
            )
            and (arguments.run_attempt is None or removed_attempt == arguments.run_attempt)
            and (arguments.source_commit is None or removed_source == arguments.source_commit)
            and (arguments.contract_sha256 is None or removed_contract == arguments.contract_sha256)
            and (arguments.target_sha256 is None or removed_target == arguments.target_sha256)
            and (arguments.expected_state is None or removed_state == arguments.expected_state)
        )
        if removed_matches:
            observed = subprocess.run(
                [
                    "aws",
                    "dynamodb",
                    "get-item",
                    "--region",
                    arguments.region,
                    "--table-name",
                    arguments.table,
                    "--key",
                    key,
                    "--consistent-read",
                    "--output",
                    "json",
                    "--no-cli-pager",
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            if observed.returncode == 0:
                try:
                    payload = json.loads(observed.stdout)
                except json.JSONDecodeError:
                    payload = {"Item": "UNREADABLE"}
                result["post_delete_item"] = payload.get("Item")
                result["lease_absent"] = not bool(payload.get("Item"))
                result["result"] = "PASS" if result["lease_absent"] else "FAIL"
                result["read_exit_code"] = observed.returncode
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    if result["result"] != "PASS":
        print("Lease release was not proved for the exact owner", file=sys.stderr)
        if deleted.stderr:
            print(deleted.stderr, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
