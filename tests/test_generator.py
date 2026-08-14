from __future__ import annotations

import json
import unittest
from pathlib import Path

from atlasretail.canonical import digest
from atlasretail.cli import _generate
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

    def test_cli_writes_exact_business_expectations(self) -> None:
        from tempfile import TemporaryDirectory

        with TemporaryDirectory() as directory:
            output = Path(directory)
            _generate(output, orders=20, seed=21, batch_id="proof-1")
            expected = json.loads((output / "expected-results.json").read_text())
            batch = generate_batch(order_count=20, seed=21)

        self.assertEqual(expected["generation_id"], "g-proof-1")
        self.assertEqual(expected["orders"], 20)
        self.assertEqual(expected["gross_cents"], sum(row.total_cents for row in batch.orders))


if __name__ == "__main__":
    unittest.main()
