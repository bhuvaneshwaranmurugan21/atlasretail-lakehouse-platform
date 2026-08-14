from __future__ import annotations

import unittest

from atlasretail.canonical import digest
from atlasretail.generator import generate_batch


class GeneratorTests(unittest.TestCase):
    def test_deterministic_generation(self) -> None:
        first = generate_batch(order_count=20, seed=21)
        second = generate_batch(order_count=20, seed=21)
        self.assertEqual(digest(first.tables()), digest(second.tables()))

    def test_different_seed_changes_payload(self) -> None:
        first = generate_batch(order_count=20, seed=21)
        second = generate_batch(order_count=20, seed=22)
        self.assertNotEqual(digest(first.tables()), digest(second.tables()))

    def test_rejects_empty_workload(self) -> None:
        with self.assertRaises(ValueError):
            generate_batch(order_count=0)


if __name__ == "__main__":
    unittest.main()
