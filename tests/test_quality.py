from __future__ import annotations

import unittest

from atlasretail.generator import (
    generate_batch,
    with_broken_total,
    with_excess_refund,
    with_missing_dimension,
    with_negative_inventory,
    with_overlapping_dimension,
)
from atlasretail.quality import resolve_product, validate


class QualityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.batch = generate_batch(order_count=30, seed=21)
        self.knowledge_time = 1_700_100_000

    def _codes(self, batch: object) -> set[str]:
        report = validate(batch, knowledge_time=self.knowledge_time)  # type: ignore[arg-type]
        return {violation.code for violation in report.violations}

    def test_valid_retail_batch(self) -> None:
        report = validate(self.batch, knowledge_time=self.knowledge_time)
        self.assertTrue(report.passed)
        self.assertEqual(30, report.metrics["orders"])
        self.assertEqual(report.metrics["gross_order_cents"], report.metrics["captured_cents"])

    def test_financial_equation(self) -> None:
        self.assertIn("ORDER_TOTAL", self._codes(with_broken_total(self.batch)))

    def test_excess_refund(self) -> None:
        self.assertIn("EXCESS_REFUND", self._codes(with_excess_refund(self.batch)))

    def test_inventory_conservation(self) -> None:
        self.assertIn("NEGATIVE_INVENTORY", self._codes(with_negative_inventory(self.batch)))

    def test_dimension_as_of_resolution(self) -> None:
        line = self.batch.order_lines[0]
        order = self.batch.orders[0]
        resolved = resolve_product(
            self.batch.products,
            product_id=line.product_id,
            event_time=order.order_ts,
            knowledge_time=self.knowledge_time,
        )
        self.assertIsNotNone(resolved)
        self.assertIn("MISSING_DIMENSION", self._codes(with_missing_dimension(self.batch)))

    def test_overlapping_dimension_is_rejected_instead_of_ranked(self) -> None:
        overlapping = with_overlapping_dimension(self.batch)
        self.assertIn("AMBIGUOUS_DIMENSION", self._codes(overlapping))
        line = overlapping.order_lines[0]
        order = overlapping.orders[0]
        self.assertIsNone(
            resolve_product(
                overlapping.products,
                product_id=line.product_id,
                event_time=order.order_ts,
                knowledge_time=self.knowledge_time,
            )
        )


if __name__ == "__main__":
    unittest.main()
