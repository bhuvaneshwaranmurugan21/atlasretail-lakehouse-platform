#!/usr/bin/env python3
"""Validate the frozen Part 4 source catalogue or a complete materialized source set."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from atlasretail.provenance import (
    CATALOG_RELATIVE_PATH,
    PROVENANCE_SCHEMA_RELATIVE_PATH,
    validate_catalog_file,
    validate_manifest_schemas,
    validate_provenance_schema_file,
    verify_materialized_sources,
)

ROOT = Path(__file__).resolve().parents[1]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, default=ROOT)
    parser.add_argument("--catalog", type=Path)
    parser.add_argument("--directory", type=Path)
    return parser.parse_args()


def main() -> int:
    arguments = parse_args()
    root = arguments.repo_root.resolve()
    catalog = arguments.catalog or root / CATALOG_RELATIVE_PATH
    result = validate_catalog_file(catalog, repo_root=root).to_dict()
    result["provenance_schema_sha256"] = validate_provenance_schema_file(
        root / PROVENANCE_SCHEMA_RELATIVE_PATH
    )
    source_schema_sha256, managed_schema_sha256 = validate_manifest_schemas(repo_root=root)
    result["source_manifest_schema_sha256"] = source_schema_sha256
    result["managed_manifest_schema_sha256"] = managed_schema_sha256
    if arguments.directory is not None:
        summary = verify_materialized_sources(arguments.directory, repo_root=root)
        result["materialized_summary_sha256"] = summary["summary_sha256"]
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
