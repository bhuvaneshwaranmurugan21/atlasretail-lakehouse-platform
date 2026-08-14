from __future__ import annotations

import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from atlasretail.engine import AtlasEngine
from atlasretail.errors import ConflictError, PublicationError
from atlasretail.generator import generate_batch
from atlasretail.manifest import build_manifest


class EngineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="atlas-engine-")
        self.addCleanup(self.temporary.cleanup)
        self.engine = AtlasEngine(Path(self.temporary.name))
        self.batch = generate_batch(order_count=12, seed=21)
        self.manifest = build_manifest(
            self.batch,
            batch_id="b-1",
            produced_at=1_700_000_900,
            as_of_knowledge_time=1_700_000_900,
        )

    def test_build_publish_and_replay(self) -> None:
        built = self.engine.build_generation(self.manifest, self.batch)
        self.assertEqual("built", built.status)
        self.assertEqual(1, self.engine.publish(built.generation_id, expected_pointer_version=0))
        replayed = self.engine.build_generation(self.manifest, self.batch)
        self.assertEqual("replayed", replayed.status)
        self.assertEqual(built.snapshot_digest, replayed.snapshot_digest)
        self.engine.assert_consistent()

    def test_conflicting_identity(self) -> None:
        self.engine.build_generation(self.manifest, self.batch)
        with self.assertRaises(ConflictError):
            self.engine.build_generation(
                replace(self.manifest, produced_at=1_700_000_901), self.batch
            )

    def test_failure_does_not_commit(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "injected failure"):
            self.engine.build_generation(self.manifest, self.batch, inject_failure=True)
        self.assertEqual((None, 0), self.engine.pointer())
        self.assertFalse((self.engine.snapshots / "g-b-1.json").exists())
        recovered = self.engine.build_generation(self.manifest, self.batch)
        self.assertEqual("built", recovered.status)

    def test_compare_and_swap_publication(self) -> None:
        built = self.engine.build_generation(self.manifest, self.batch)
        self.engine.publish(built.generation_id, expected_pointer_version=0)
        second_batch = generate_batch(order_count=6, seed=84)
        second_manifest = build_manifest(
            second_batch,
            batch_id="b-2",
            produced_at=1_700_001_000,
            as_of_knowledge_time=1_700_001_000,
        )
        second = self.engine.build_generation(second_manifest, second_batch)
        with self.assertRaisesRegex(PublicationError, "stale pointer"):
            self.engine.publish(second.generation_id, expected_pointer_version=0)
        self.assertEqual(2, self.engine.publish(second.generation_id, expected_pointer_version=1))
        self.assertEqual((second.generation_id, 2), self.engine.pointer())


if __name__ == "__main__":
    unittest.main()
