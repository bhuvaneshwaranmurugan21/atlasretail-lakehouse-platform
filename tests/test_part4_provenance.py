from __future__ import annotations

import copy
import json
import os
import subprocess
import sys
import tempfile
import unittest
import zlib
from pathlib import Path

from atlasretail.provenance import (
    CATALOG_RELATIVE_PATH,
    PROVENANCE_SCHEMA_RELATIVE_PATH,
    ProvenanceError,
    deterministic_gzip,
    generate_source_data,
    materialize_part4_sources,
    validate_catalog,
    validate_catalog_file,
    validate_order_count,
    validate_provenance_schema_file,
    verify_materialized_sources,
    verify_receipt,
)

ROOT = Path(__file__).parents[1]
SOURCE_COMMIT = "6e54722bd6362d172b9c178523652d7a725ca485"


def load_catalog() -> dict[str, object]:
    return json.loads((ROOT / CATALOG_RELATIVE_PATH).read_text(encoding="utf-8"))


def file_bytes(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file()
    }


class Part4SourceCatalogTests(unittest.TestCase):
    def test_catalog_and_receipt_schema_are_bound_and_valid(self) -> None:
        result = validate_catalog_file(ROOT / CATALOG_RELATIVE_PATH, repo_root=ROOT)
        schema_digest = validate_provenance_schema_file(ROOT / PROVENANCE_SCHEMA_RELATIVE_PATH)
        self.assertEqual(10, result.scenario_count)
        self.assertEqual(5, result.source_family_count)
        self.assertEqual(64, len(schema_digest))

    def test_catalog_rejects_contract_drift(self) -> None:
        catalog = load_catalog()
        catalog["contract_sha256"] = "0" * 64
        with self.assertRaisesRegex(ProvenanceError, "catalog.contract_sha256"):
            validate_catalog(catalog, repo_root=ROOT)

    def test_catalog_rejects_missing_scenario(self) -> None:
        catalog = load_catalog()
        del catalog["scenario_bindings"]["replay"]  # type: ignore[index]
        with self.assertRaisesRegex(ProvenanceError, "scenario_bindings.names"):
            validate_catalog(catalog, repo_root=ROOT)

    def test_catalog_rejects_substitute_recovery_source(self) -> None:
        catalog = load_catalog()
        catalog["scenario_bindings"]["recovery"]["source_family"] = "success"  # type: ignore[index]
        with self.assertRaisesRegex(ProvenanceError, "scenario_bindings.recovery"):
            validate_catalog(catalog, repo_root=ROOT)

    def test_catalog_rejects_duplicate_seed(self) -> None:
        catalog = load_catalog()
        catalog["source_families"]["tamper"]["seed"] = 21  # type: ignore[index]
        with self.assertRaisesRegex(ProvenanceError, "unique seed"):
            validate_catalog(catalog, repo_root=ROOT)

    def test_part4_order_bounds_are_exact(self) -> None:
        self.assertEqual(100, validate_order_count(100))
        self.assertEqual(500, validate_order_count(500))
        self.assertEqual(2000, validate_order_count(2000))
        for invalid in (True, 99, 2001, -1, "500"):
            with self.subTest(invalid=invalid), self.assertRaises(ProvenanceError):
                validate_order_count(invalid)


class DeterministicSourceTests(unittest.TestCase):
    def test_gzip_header_and_payload_are_fully_deterministic(self) -> None:
        payload = b'{"id":"one"}\n'
        first = deterministic_gzip(payload)
        second = deterministic_gzip(payload)
        self.assertEqual(first, second)
        self.assertEqual(b"\x1f\x8b\x08\x00\x00\x00\x00\x00\x02\xff", first[:10])
        self.assertEqual(payload, zlib.decompress(first, wbits=31))

    def test_complete_materialization_is_byte_identical_across_directories(self) -> None:
        with (
            tempfile.TemporaryDirectory() as first_dir,
            tempfile.TemporaryDirectory() as second_dir,
        ):
            first = Path(first_dir)
            second = Path(second_dir)
            first_summary = materialize_part4_sources(
                first,
                repo_root=ROOT,
                order_count=100,
                source_commit=SOURCE_COMMIT,
                run_id="proof",
            )
            second_summary = materialize_part4_sources(
                second,
                repo_root=ROOT,
                order_count=100,
                source_commit=SOURCE_COMMIT,
                run_id="proof",
            )
            self.assertEqual(first_summary, second_summary)
            self.assertEqual(file_bytes(first), file_bytes(second))

    def test_complete_materialization_is_independent_of_timezone_and_hash_seed(self) -> None:
        with (
            tempfile.TemporaryDirectory() as first_dir,
            tempfile.TemporaryDirectory() as second_dir,
        ):
            command = [
                sys.executable,
                "-m",
                "atlasretail.cli",
                "generate-sources",
                "--orders",
                "100",
                "--source-commit",
                SOURCE_COMMIT,
                "--run-id",
                "environment-proof",
            ]
            first_environment = {**os.environ, "PYTHONHASHSEED": "1", "TZ": "UTC"}
            second_environment = {**os.environ, "PYTHONHASHSEED": "987", "TZ": "Asia/Kolkata"}
            subprocess.run(
                [*command, "--output", first_dir],
                cwd=ROOT,
                env=first_environment,
                check=True,
                capture_output=True,
                text=True,
            )
            subprocess.run(
                [*command, "--output", second_dir],
                cwd=ROOT,
                env=second_environment,
                check=True,
                capture_output=True,
                text=True,
            )
            self.assertEqual(file_bytes(Path(first_dir)), file_bytes(Path(second_dir)))

    def test_changed_seed_changes_bundle_identity(self) -> None:
        with (
            tempfile.TemporaryDirectory() as first_dir,
            tempfile.TemporaryDirectory() as second_dir,
        ):
            first = Path(first_dir)
            second = Path(second_dir)
            common = {
                "orders": 100,
                "batch_id": "seed-proof",
                "fault": "none",
            }
            generate_source_data(first, seed=21, **common)
            generate_source_data(second, seed=22, **common)
            self.assertNotEqual(
                next((first / "orders").glob("*.jsonl.gz")).read_bytes(),
                next((second / "orders").glob("*.jsonl.gz")).read_bytes(),
            )


class ProvenanceAdversarialTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.output = Path(self.temporary.name)
        materialize_part4_sources(
            self.output,
            repo_root=ROOT,
            order_count=100,
            source_commit=SOURCE_COMMIT,
            run_id="adversarial",
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_independent_validation_accepts_complete_sources(self) -> None:
        summary = verify_materialized_sources(self.output, repo_root=ROOT)
        self.assertEqual("PASS", summary["result"])
        self.assertEqual(5, len(summary["receipts"]))
        self.assertNotIn("recovery", {path.name for path in self.output.iterdir()})

    def test_modified_compressed_object_is_rejected(self) -> None:
        path = next((self.output / "success" / "orders").glob("*.jsonl.gz"))
        path.write_bytes(path.read_bytes() + b"contradiction")
        with self.assertRaises(ProvenanceError):
            verify_materialized_sources(self.output, repo_root=ROOT)

    def test_contradictory_expected_business_result_is_rejected(self) -> None:
        path = self.output / "success" / "expected-results.json"
        expected = json.loads(path.read_text(encoding="utf-8"))
        expected["gross_cents"] += 1
        path.write_text(json.dumps(expected), encoding="utf-8")
        with self.assertRaisesRegex(ProvenanceError, "expected_results"):
            verify_materialized_sources(self.output, repo_root=ROOT)

    def test_undeclared_regular_file_is_rejected(self) -> None:
        (self.output / "success" / "undeclared.bin").write_bytes(b"not-in-source-contract")
        with self.assertRaisesRegex(ProvenanceError, "sources.success.files"):
            verify_materialized_sources(self.output, repo_root=ROOT)

    def test_changed_receipt_without_rehash_is_rejected(self) -> None:
        path = self.output / "success" / "source-provenance.json"
        receipt = json.loads(path.read_text(encoding="utf-8"))
        receipt["source_commit"] = "f" * 40
        path.write_text(json.dumps(receipt), encoding="utf-8")
        with self.assertRaisesRegex(ProvenanceError, "receipt_sha256"):
            verify_materialized_sources(self.output, repo_root=ROOT)

    def test_missing_receipt_field_is_rejected(self) -> None:
        directory = self.output / "success"
        path = directory / "source-provenance.json"
        receipt = json.loads(path.read_text(encoding="utf-8"))
        del receipt["source_manifest_schema_sha256"]
        catalog = load_catalog()
        with self.assertRaisesRegex(ProvenanceError, "receipt.keys"):
            verify_receipt(receipt, directory=directory, repo_root=ROOT, catalog=catalog)

    def test_symlinked_input_is_rejected(self) -> None:
        directory = self.output / "success"
        link = directory / "undeclared-link"
        try:
            link.symlink_to(directory / "manifest.json")
        except OSError as error:
            self.skipTest(f"symlinks unavailable: {error}")
        catalog = load_catalog()
        receipt = json.loads((directory / "source-provenance.json").read_text(encoding="utf-8"))
        with self.assertRaisesRegex(ProvenanceError, "source.symlink"):
            verify_receipt(receipt, directory=directory, repo_root=ROOT, catalog=catalog)

    def test_changed_tamper_replacement_is_rejected(self) -> None:
        replacement = self.output / "tamper" / "tamper-replacement.bin"
        replacement.write_bytes(b"different-undocumented-corruption")
        with self.assertRaisesRegex(ProvenanceError, "replacement_sha256"):
            verify_materialized_sources(self.output, repo_root=ROOT)

    def test_summary_digest_is_enforced(self) -> None:
        path = self.output / "source-provenance-summary.json"
        summary = json.loads(path.read_text(encoding="utf-8"))
        summary["order_count"] = 101
        path.write_text(json.dumps(summary), encoding="utf-8")
        with self.assertRaisesRegex(ProvenanceError, "summary_sha256"):
            verify_materialized_sources(self.output, repo_root=ROOT)

    def test_substitute_source_commit_is_rejected_by_complete_set(self) -> None:
        directory = self.output / "success"
        path = directory / "source-provenance.json"
        receipt = json.loads(path.read_text(encoding="utf-8"))
        receipt["source_commit"] = "f" * 40
        payload = copy.deepcopy(receipt)
        del payload["receipt_sha256"]
        from atlasretail.canonical import digest

        receipt["receipt_sha256"] = digest(payload)
        path.write_text(json.dumps(receipt), encoding="utf-8")
        with self.assertRaisesRegex(ProvenanceError, "sources.source_commits"):
            verify_materialized_sources(self.output, repo_root=ROOT)


if __name__ == "__main__":
    unittest.main()
