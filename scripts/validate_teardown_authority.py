#!/usr/bin/env python3
"""Validate current or explicitly selected legacy controlled-deployment authority."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from terraform_source_digest import DIGEST_SCHEME, source_digest


def legacy_post_init_digest(terraform_root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(terraform_root.rglob("*")):
        if path.is_file() and ".terraform" not in path.parts:
            digest.update(path.relative_to(terraform_root).as_posix().encode())
            digest.update(path.read_bytes())
    return "sha256:" + digest.hexdigest()


def validate(
    manifest: dict[str, Any],
    *,
    repository: str,
    run_id: str,
    source_commit: str,
    account: str,
    region: str,
    backend_bucket: str,
    backend_key: str,
    repository_root: Path,
    legacy_terraform_root: Path | None = None,
) -> dict[str, Any]:
    expected = {
        "project": "AtlasRetail",
        "operation": "controlled-deployment",
        "repository": repository,
        "run_id": run_id,
        "source_commit": source_commit,
        "account": account,
        "region": region,
        "backend_bucket": backend_bucket,
        "backend_key": backend_key,
    }
    errors = [f"{name} mismatch" for name, value in expected.items() if manifest.get(name) != value]

    scheme = manifest.get("infrastructure_digest_scheme")
    if scheme == DIGEST_SCHEME:
        observed_digest = source_digest(repository_root)
    elif scheme is None and legacy_terraform_root is not None:
        scheme = "legacy-post-init-v1"
        observed_digest = legacy_post_init_digest(legacy_terraform_root)
    else:
        errors.append("unsupported infrastructure digest scheme")
        observed_digest = "UNAVAILABLE"

    if manifest.get("infrastructure_digest") != observed_digest:
        errors.append("infrastructure digest mismatch")

    return {
        "result": "PASS" if not errors else "FAIL",
        "claim": "IMMUTABLE_TEARDOWN_AUTHORITY_VERIFIED" if not errors else "NONE",
        "repository": repository,
        "run_id": run_id,
        "source_commit": source_commit,
        "account": account,
        "region": region,
        "infrastructure_digest_scheme": scheme,
        "expected_infrastructure_digest": manifest.get("infrastructure_digest"),
        "observed_infrastructure_digest": observed_digest,
        "errors": errors,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--account", required=True)
    parser.add_argument("--region", required=True)
    parser.add_argument("--backend-bucket", required=True)
    parser.add_argument("--backend-key", required=True)
    parser.add_argument("--repository-root", type=Path, default=Path("."))
    parser.add_argument("--legacy-terraform-root", type=Path)
    args = parser.parse_args()

    try:
        manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
        if not isinstance(manifest, dict):
            raise ValueError("authority manifest must be a JSON object")
        proof = validate(
            manifest,
            repository=args.repository,
            run_id=args.run_id,
            source_commit=args.source_commit,
            account=args.account,
            region=args.region,
            backend_bucket=args.backend_bucket,
            backend_key=args.backend_key,
            repository_root=args.repository_root,
            legacy_terraform_root=args.legacy_terraform_root,
        )
    except (OSError, ValueError, json.JSONDecodeError) as error:
        proof = {"result": "FAIL", "claim": "NONE", "errors": [str(error)]}

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(proof, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if proof["result"] != "PASS":
        print(json.dumps(proof, indent=2, sort_keys=True))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
