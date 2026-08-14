"""Retail-specific correctness gates."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import TypeVar

from .model import OrderLine, ProductVersion, RetailBatch


@dataclass(frozen=True, slots=True)
class Violation:
    code: str
    entity_id: str
    message: str


@dataclass(frozen=True, slots=True)
class QualityReport:
    violations: tuple[Violation, ...]
    metrics: dict[str, int]

    @property
    def passed(self) -> bool:
        return not self.violations


T = TypeVar("T")


def _duplicates(values: Iterable[T]) -> set[T]:
    seen: set[T] = set()
    repeated: set[T] = set()
    for value in values:
        if value in seen:
            repeated.add(value)
        seen.add(value)
    return repeated


def resolve_product(
    versions: Iterable[ProductVersion],
    *,
    product_id: str,
    event_time: int,
    knowledge_time: int,
) -> ProductVersion | None:
    candidates = [
        version
        for version in versions
        if version.product_id == product_id
        and version.effective_from <= event_time
        and (version.effective_to is None or event_time < version.effective_to)
        and version.loaded_at <= knowledge_time
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda value: (value.loaded_at, value.effective_from))


def validate(batch: RetailBatch, *, knowledge_time: int) -> QualityReport:
    violations: list[Violation] = []

    identifiers = {
        "order": [row.order_id for row in batch.orders],
        "line": [f"{row.order_id}:{row.line_id}" for row in batch.order_lines],
        "payment": [row.payment_id for row in batch.payments],
        "return": [row.return_id for row in batch.returns],
        "movement": [row.movement_id for row in batch.inventory_movements],
    }
    for entity, values in identifiers.items():
        for value in sorted(_duplicates(values)):
            violations.append(Violation("DUPLICATE_ID", str(value), f"duplicate {entity} identity"))

    orders = {order.order_id: order for order in batch.orders}
    lines_by_order: dict[str, list[OrderLine]] = {}
    line_lookup: dict[tuple[str, str], OrderLine] = {}
    for line in batch.order_lines:
        lines_by_order.setdefault(line.order_id, []).append(line)
        line_lookup[(line.order_id, line.line_id)] = line
        if line.quantity <= 0 or line.unit_price_cents < 0:
            violations.append(
                Violation("INVALID_LINE", line.line_id, "quantity and price must be valid")
            )
        if line.line_total_cents != line.quantity * line.unit_price_cents:
            violations.append(
                Violation("LINE_TOTAL", line.line_id, "line total is not quantity * price")
            )

    for order in batch.orders:
        lines = lines_by_order.get(order.order_id, [])
        subtotal = sum(line.line_total_cents for line in lines)
        if subtotal != order.subtotal_cents:
            violations.append(
                Violation("ORDER_SUBTOTAL", order.order_id, "line sum differs from subtotal")
            )
        expected_total = order.subtotal_cents + order.tax_cents - order.discount_cents
        if expected_total != order.total_cents:
            violations.append(
                Violation("ORDER_TOTAL", order.order_id, "financial equation does not balance")
            )
        if order.currency not in {"INR", "USD"}:
            violations.append(Violation("CURRENCY", order.order_id, "unsupported currency"))

    captured_by_order: dict[str, int] = {}
    for payment in batch.payments:
        if payment.order_id not in orders:
            violations.append(Violation("ORPHAN_PAYMENT", payment.payment_id, "order is missing"))
        if payment.status == "CAPTURED":
            captured_by_order[payment.order_id] = (
                captured_by_order.get(payment.order_id, 0) + payment.amount_cents
            )
    for order in batch.orders:
        if (
            order.status == "COMPLETED"
            and captured_by_order.get(order.order_id, 0) < order.total_cents
        ):
            violations.append(
                Violation("UNDERPAID", order.order_id, "captured payment is below order total")
            )

    refunded_by_order: dict[str, int] = {}
    returned_qty: dict[tuple[str, str], int] = {}
    for returned in batch.returns:
        key = (returned.order_id, returned.line_id)
        returned_line = line_lookup.get(key)
        if returned_line is None:
            violations.append(
                Violation("ORPHAN_RETURN", returned.return_id, "order line is missing")
            )
            continue
        returned_qty[key] = returned_qty.get(key, 0) + returned.quantity
        refunded_by_order[returned.order_id] = (
            refunded_by_order.get(returned.order_id, 0) + returned.refund_cents
        )
        if returned.quantity <= 0 or returned.refund_cents < 0:
            violations.append(
                Violation("INVALID_RETURN", returned.return_id, "return values must be positive")
            )
    for key, quantity in returned_qty.items():
        line = line_lookup[key]
        if quantity > line.quantity:
            violations.append(
                Violation("RETURN_QUANTITY", ":".join(key), "returned quantity exceeds ordered")
            )
    for order_id, refund in refunded_by_order.items():
        if refund > captured_by_order.get(order_id, 0):
            violations.append(
                Violation("EXCESS_REFUND", order_id, "refund exceeds captured payment")
            )

    inventory: dict[tuple[str, str], int] = {}
    for movement in sorted(batch.inventory_movements, key=lambda value: value.movement_ts):
        key = (movement.product_id, movement.store_id)
        inventory[key] = inventory.get(key, 0) + movement.quantity_delta
        if inventory[key] < 0:
            violations.append(
                Violation(
                    "NEGATIVE_INVENTORY",
                    f"{movement.product_id}:{movement.store_id}",
                    "stock fell below zero",
                )
            )

    for line in batch.order_lines:
        parent_order = orders.get(line.order_id)
        if parent_order is None:
            violations.append(Violation("ORPHAN_LINE", line.line_id, "order is missing"))
            continue
        version = resolve_product(
            batch.products,
            product_id=line.product_id,
            event_time=parent_order.order_ts,
            knowledge_time=knowledge_time,
        )
        if version is None:
            violations.append(
                Violation(
                    "MISSING_DIMENSION",
                    line.product_id,
                    "no knowable product version for order time",
                )
            )

    metrics = {
        "orders": len(batch.orders),
        "order_lines": len(batch.order_lines),
        "payments": len(batch.payments),
        "returns": len(batch.returns),
        "inventory_movements": len(batch.inventory_movements),
        "products": len(batch.products),
        "gross_order_cents": sum(order.total_cents for order in batch.orders),
        "captured_cents": sum(captured_by_order.values()),
        "refunded_cents": sum(refunded_by_order.values()),
    }
    return QualityReport(tuple(violations), metrics)
