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
    values = json.dumps(expected, separators=(",", ":"))
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
        "result": "FAIL",
        "owner": arguments.owner,
        "lease_absent": False,
        "consistent_read": True,
        "delete_exit_code": deleted.returncode,
        "authority_sha256": arguments.authority_sha256,
        "run_attempt": arguments.run_attempt,
        "source_commit": arguments.source_commit,
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
        removed_matches = (
            removed_owner == arguments.owner
            and (
                arguments.authority_sha256 is None
                or removed_authority == arguments.authority_sha256
            )
            and (arguments.run_attempt is None or removed_attempt == arguments.run_attempt)
            and (arguments.source_commit is None or removed_source == arguments.source_commit)
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
