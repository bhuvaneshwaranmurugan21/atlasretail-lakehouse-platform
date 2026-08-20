from __future__ import annotations

import unittest
from dataclasses import replace

from atlasretail.errors import ManifestError
from atlasretail.generator import generate_batch
from atlasretail.manifest import (
    ObjectProof,
    bind_objects,
    build_manifest,
    manifest_from_dict,
    verify_managed_manifest,
    verify_manifest,
)


class ManifestTests(unittest.TestCase):
    def setUp(self) -> None:
        self.batch = generate_batch(order_count=8, seed=21)
        self.manifest = build_manifest(
            self.batch,
            batch_id="b-1",
            produced_at=1_700_000_500,
            as_of_knowledge_time=1_700_000_500,
        )

    def test_valid_manifest(self) -> None:
        verify_manifest(self.manifest, self.batch)

    def test_changed_payload_is_rejected(self) -> None:
        changed = replace(self.batch, orders=self.batch.orders[:-1])
        with self.assertRaisesRegex(ManifestError, "row count mismatch"):
            verify_manifest(self.manifest, changed)

    def test_unknown_contract_is_rejected(self) -> None:
        with self.assertRaisesRegex(ManifestError, "unsupported contract"):
            verify_manifest(replace(self.manifest, contract_version="retail-v1"), self.batch)

    def test_managed_manifest_binds_every_table_to_an_exact_version(self) -> None:
        objects = {
            name: (
                ObjectProof(
                    bucket="landing-bucket",
                    key=f"runs/b-1/{name}/part.jsonl.gz",
                    version_id=f"version-{name}",
                    size_bytes=100,
                    sha256="a" * 64,
                    etag=f"etag-{name}",
                ),
            )
            for name in self.manifest.tables
        }
        managed = bind_objects(self.manifest, objects)
        verify_managed_manifest(managed)
        self.assertEqual(managed, manifest_from_dict(managed.to_dict()))

    def test_changed_canonical_manifest_digest_is_rejected(self) -> None:
        value = self.manifest.to_dict()
        value["produced_at"] += 1
        with self.assertRaisesRegex(ManifestError, "identity digest"):
            manifest_from_dict(value)

    def test_managed_manifest_rejects_missing_object_identity(self) -> None:
        with self.assertRaisesRegex(ManifestError, "not bound"):
            verify_managed_manifest(self.manifest)


if __name__ == "__main__":
    unittest.main()
