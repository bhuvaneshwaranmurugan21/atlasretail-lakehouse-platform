"""Upload one generated batch and bind its manifest to exact S3 object versions."""

from __future__ import annotations

import argparse
import base64
import gzip
import hashlib
import json
import subprocess
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from atlasretail.canonical import digest_records
from atlasretail.manifest import ObjectProof, bind_objects, manifest_from_dict


def aws(*arguments: str) -> dict[str, Any]:
    command = ["aws", "s3api", *arguments, "--output", "json", "--no-cli-pager"]
    result = subprocess.run(command, check=True, capture_output=True, text=True)
    return json.loads(result.stdout)


def upload(path: Path, *, bucket: str, key: str, kms_key: str) -> ObjectProof:
    content = path.read_bytes()
    sha256 = hashlib.sha256(content).hexdigest()
    response = aws(
        "put-object",
        "--bucket",
        bucket,
        "--key",
        key,
        "--body",
        str(path),
        "--server-side-encryption",
        "aws:kms",
        "--ssekms-key-id",
        kms_key,
        "--checksum-algorithm",
        "SHA256",
    )
    checksum = response.get("ChecksumSHA256")
    if checksum is None or base64.b64decode(checksum).hex() != sha256:
        raise RuntimeError(f"S3 did not confirm the SHA-256 checksum for {path}")
    version_id = response.get("VersionId")
    if not version_id:
        raise RuntimeError(f"S3 versioning evidence is absent for {path}")
    return ObjectProof(
        bucket=bucket,
        key=key,
        version_id=str(version_id),
        size_bytes=len(content),
        sha256=sha256,
        etag=str(response["ETag"]).strip('"'),
    )


def generated_records(paths: list[Path]) -> Iterator[dict[str, Any]]:
    """Read generated NDJSON in manifest order without retaining a table in memory."""
    for path in paths:
        with gzip.open(path, "rt", encoding="utf-8") as stream:
            for line in stream:
                value = json.loads(line)
                if not isinstance(value, dict):
                    raise RuntimeError(f"generated record is not a JSON object: {path}")
                yield value


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--bucket", required=True)
    parser.add_argument("--prefix", required=True)
    parser.add_argument("--kms-key", required=True)
    parser.add_argument("--managed-manifest-output", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()

    local_manifest = manifest_from_dict(
        json.loads((arguments.directory / "manifest.json").read_text(encoding="utf-8"))
    )
    files_by_table: dict[str, list[Path]] = {}
    for table in sorted(local_manifest.tables):
        files = sorted((arguments.directory / table).glob("*.jsonl.gz"))
        if not files:
            raise RuntimeError(f"no generated objects found for {table}")
        actual_rows, actual_digest = digest_records(generated_records(files))
        expected = local_manifest.tables[table]
        if actual_rows != expected.rows or actual_digest != expected.sha256:
            raise RuntimeError(f"generated table does not match its manifest proof: {table}")
        files_by_table[table] = files

    object_map: dict[str, tuple[ObjectProof, ...]] = {}
    for table, files in files_by_table.items():
        object_map[table] = tuple(
            upload(
                path,
                bucket=arguments.bucket,
                key=f"{arguments.prefix.rstrip('/')}/{table}/{path.name}",
                kms_key=arguments.kms_key,
            )
            for path in files
        )

    managed = bind_objects(local_manifest, object_map)
    managed_path = (
        arguments.managed_manifest_output or arguments.directory / "managed-manifest.json"
    )
    managed_path.parent.mkdir(parents=True, exist_ok=True)
    managed_path.write_text(
        json.dumps(managed.to_dict(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    manifest_object = upload(
        managed_path,
        bucket=arguments.bucket,
        key=f"{arguments.prefix.rstrip('/')}/managed-manifest.json",
        kms_key=arguments.kms_key,
    )
    result = {
        "batch_id": managed.batch_id,
        "identity_digest": managed.identity_digest,
        "manifest_uri": f"s3://{manifest_object.bucket}/{manifest_object.key}",
        "manifest_version_id": manifest_object.version_id,
        "manifest_object": {
            "bucket": manifest_object.bucket,
            "key": manifest_object.key,
            "version_id": manifest_object.version_id,
            "size_bytes": manifest_object.size_bytes,
            "sha256": manifest_object.sha256,
            "etag": manifest_object.etag,
        },
        "tables": {
            name: [
                {
                    "bucket": item.bucket,
                    "key": item.key,
                    "version_id": item.version_id,
                    "size_bytes": item.size_bytes,
                    "sha256": item.sha256,
                    "etag": item.etag,
                }
                for item in objects
            ]
            for name, objects in sorted(object_map.items())
        },
    }
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


if __name__ == "__main__":
    main()
