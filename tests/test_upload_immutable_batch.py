from __future__ import annotations

import gzip
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from atlasretail.cli import _generate

SCRIPT = Path(__file__).parents[1] / "scripts" / "upload_immutable_batch.py"
SPEC = importlib.util.spec_from_file_location("atlasretail_immutable_upload", SCRIPT)
assert SPEC and SPEC.loader
UPLOAD = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(UPLOAD)


class ImmutableUploadTests(unittest.TestCase):
    def test_generated_records_are_read_in_declared_file_order(self) -> None:
        with tempfile.TemporaryDirectory(prefix="atlas-upload-") as directory:
            first = Path(directory) / "01.jsonl.gz"
            second = Path(directory) / "02.jsonl.gz"
            with gzip.open(first, "wt", encoding="utf-8") as stream:
                stream.write('{"id":"a"}\n')
            with gzip.open(second, "wt", encoding="utf-8") as stream:
                stream.write('{"id":"b"}\n')
            self.assertEqual(
                list(UPLOAD.generated_records([first, second])),
                [{"id": "a"}, {"id": "b"}],
            )

    def test_manifest_mismatch_is_rejected_before_any_s3_upload(self) -> None:
        with tempfile.TemporaryDirectory(prefix="atlas-upload-") as directory:
            output = Path(directory)
            _generate(output, orders=3, seed=21, batch_id="proof-1", fault="none")
            path = next((output / "orders").glob("*.jsonl.gz"))
            with gzip.open(path, "rt", encoding="utf-8") as stream:
                rows = [json.loads(line) for line in stream]
            rows[0]["currency"] = "EUR"
            with gzip.open(path, "wt", encoding="utf-8") as stream:
                for row in rows:
                    stream.write(json.dumps(row) + "\n")

            arguments = [
                str(SCRIPT),
                "--directory",
                str(output),
                "--bucket",
                "landing",
                "--prefix",
                "runs/proof-1",
                "--kms-key",
                "key",
                "--output",
                str(output / "uploaded.json"),
            ]
            with (
                patch.object(sys, "argv", arguments),
                patch.object(UPLOAD, "upload") as upload,
                self.assertRaisesRegex(RuntimeError, "manifest proof: orders"),
            ):
                UPLOAD.main()
            upload.assert_not_called()
