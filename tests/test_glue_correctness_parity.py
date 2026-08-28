from __future__ import annotations

import ast
import base64
import gzip
import hashlib
import importlib.util
import json
import unittest
from io import BytesIO
from pathlib import Path
from typing import Any

from atlasretail.canonical import digest

ROOT = Path(__file__).parents[1]
GLUE_PATH = ROOT / "aws" / "glue" / "atlasretail_iceberg.py"
QUALITY_PATH = ROOT / "src" / "atlasretail" / "quality.py"
SPEC = importlib.util.spec_from_file_location("atlasretail_managed_glue", GLUE_PATH)
assert SPEC and SPEC.loader
GLUE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(GLUE)

MANAGED_ONLY_GATES = {
    "MANIFEST_DIGEST",
    "MANIFEST_IDENTITY",
    "MANIFEST_TABLE_SET",
    "OBJECT_CHECKSUM",
    "OBJECT_CONTENT",
    "OBJECT_IDENTITY",
    "ROW_COUNT",
    "S3_URI",
    "TABLE_DIGEST",
}


def emitted_codes(path: Path, constructor: str) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    values: set[str] = set()
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == constructor
            and node.args
            and isinstance(node.args[0], ast.Constant)
            and isinstance(node.args[0].value, str)
        ):
            values.add(node.args[0].value)
    return values


def compressed_rows(rows: list[dict[str, Any]]) -> bytes:
    payload = "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows)
    return gzip.compress(payload.encode("utf-8"))


class FakeS3:
    def __init__(self, versions: dict[str, bytes]) -> None:
        self.versions = versions
        self.calls: list[tuple[str, str, str]] = []

    def get_object(self, *, Bucket: str, Key: str, VersionId: str) -> dict[str, BytesIO]:
        self.calls.append((Bucket, Key, VersionId))
        return {"Body": BytesIO(self.versions[VersionId])}


class FakeIdentityS3:
    def head_object(self, **_: str) -> dict[str, object]:
        corrupted = b"deliberately-corrupted-object"
        return {
            "ContentLength": len(corrupted),
            "ChecksumSHA256": base64.b64encode(hashlib.sha256(corrupted).digest()).decode(),
            "ETag": '"corrupted-etag"',
        }


class ManagedCorrectnessParityTests(unittest.TestCase):
    def test_local_and_managed_business_gates_are_identical(self) -> None:
        local = emitted_codes(QUALITY_PATH, "Violation")
        managed = emitted_codes(GLUE_PATH, "fail")
        self.assertEqual(managed - MANAGED_ONLY_GATES, local)
        self.assertEqual(managed & MANAGED_ONLY_GATES, MANAGED_ONLY_GATES)

    def test_glue_script_can_be_imported_without_aws_or_spark(self) -> None:
        self.assertTrue(callable(GLUE.main))
        self.assertTrue(callable(GLUE.validate_frames))
        self.assertTrue(callable(GLUE.build_generation))

    def test_streaming_table_digest_matches_existing_manifest_contract(self) -> None:
        rows = [{"currency": "₹", "amount": 42}, {"amount": 7, "currency": "USD"}]
        actual = GLUE.canonical_table_digest([BytesIO(compressed_rows(rows))])
        self.assertEqual(actual, (len(rows), digest(rows)))

    def test_multiple_objects_preserve_manifest_order(self) -> None:
        first = [{"id": "a"}, {"id": "b"}]
        second = [{"id": "c"}]
        actual = GLUE.canonical_table_digest(
            [BytesIO(compressed_rows(first)), BytesIO(compressed_rows(second))]
        )
        self.assertEqual(actual, (3, digest([*first, *second])))

    def test_same_row_count_with_different_content_is_rejected(self) -> None:
        declared = [{"id": "expected"}]
        actual = [{"id": "substituted"}]
        s3 = FakeS3({"version-1": compressed_rows(actual)})
        proof = {
            "rows": 1,
            "sha256": digest(declared),
            "objects": [{"bucket": "landing", "key": "orders.gz", "version_id": "version-1"}],
        }
        with self.assertRaisesRegex(ValueError, "QUALITY_GATE:TABLE_DIGEST:orders"):
            GLUE.verify_table_digest(s3, table="orders", proof=proof)
        self.assertEqual(s3.calls, [("landing", "orders.gz", "version-1")])

    def test_registered_row_count_is_verified_before_spark_read(self) -> None:
        rows = [{"id": "a"}, {"id": "b"}]
        s3 = FakeS3({"version-2": compressed_rows(rows)})
        proof = {
            "rows": 1,
            "sha256": digest(rows),
            "objects": [{"bucket": "landing", "key": "orders.gz", "version_id": "version-2"}],
        }
        with self.assertRaisesRegex(ValueError, "QUALITY_GATE:ROW_COUNT:orders"):
            GLUE.verify_table_digest(s3, table="orders", proof=proof)

    def test_non_object_ndjson_record_is_rejected(self) -> None:
        payload = gzip.compress(b"7\n")
        with self.assertRaisesRegex(ValueError, "QUALITY_GATE:OBJECT_CONTENT"):
            GLUE.canonical_table_digest([BytesIO(payload)])

    def test_registered_s3_version_with_contradictory_bytes_is_rejected_before_spark(self) -> None:
        manifest = {
            "tables": {
                "orders": {
                    "objects": [
                        {
                            "bucket": "landing",
                            "key": "orders.jsonl.gz",
                            "version_id": "tampered-version",
                            "size_bytes": 42,
                            "sha256": "0" * 64,
                            "etag": "registered-etag",
                        }
                    ]
                }
            }
        }
        with self.assertRaisesRegex(ValueError, "QUALITY_GATE:OBJECT_IDENTITY:orders"):
            GLUE.load_registered_frames(
                object(),
                FakeIdentityS3(),
                args={"GENERATION_ID": "g-tamper"},
                manifest=manifest,
                manifest_bucket="landing",
            )
