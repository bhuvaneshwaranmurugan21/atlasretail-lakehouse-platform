#!/usr/bin/env python3
"""Validate and identify the frozen AtlasRetail Part 4 execution contract."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from atlasretail.part4_contract import CONTRACT_RELATIVE_PATH, validate_part4_contract_file

ROOT = Path(__file__).resolve().parents[1]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--contract", type=Path, default=ROOT / CONTRACT_RELATIVE_PATH)
    parser.add_argument("--repo-root", type=Path, default=ROOT)
    return parser.parse_args()


def main() -> int:
    arguments = parse_args()
    result = validate_part4_contract_file(arguments.contract, repo_root=arguments.repo_root)
    print(json.dumps(result.to_dict(), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
