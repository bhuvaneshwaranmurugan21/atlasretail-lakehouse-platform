#!/usr/bin/env python3
"""Build immutable teardown authority from the pristine checked-in source."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from terraform_source_digest import DIGEST_SCHEME, source_digest


def authority(environment: dict[str, str], repository: Path = Path(".")) -> dict[str, str]:
    return {
        "schema_version": "2.0",
        "project": "AtlasRetail",
        "operation": "controlled-deployment",
        "repository": environment["GITHUB_REPOSITORY"],
        "run_id": environment["GITHUB_RUN_ID"],
        "source_commit": environment["GITHUB_SHA"],
        "account": environment["AWS_ACCOUNT_ID"],
        "region": environment["AWS_REGION"],
        "backend_bucket": environment["TERRAFORM_STATE_BUCKET"],
        "backend_key": environment["TERRAFORM_STATE_KEY"],
        "infrastructure_digest_scheme": DIGEST_SCHEME,
        "infrastructure_digest": source_digest(repository),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    value = authority(dict(os.environ))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
