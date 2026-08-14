from __future__ import annotations

import unittest
from dataclasses import replace

from atlasretail.errors import ManifestError
from atlasretail.generator import generate_batch
from atlasretail.manifest import build_manifest, verify_manifest


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
            verify_manifest(replace(self.manifest, contract_version="retail-v2"), self.batch)


if __name__ == "__main__":
    unittest.main()
