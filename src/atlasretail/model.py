"""Immutable domain records for the retail workload."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class Order:
    order_id: str
    customer_id: str
    store_id: str
    order_ts: int
    status: str
    subtotal_cents: int
    tax_cents: int
    discount_cents: int
    total_cents: int
    currency: str


@dataclass(frozen=True, slots=True)
class OrderLine:
    order_id: str
    line_id: str
    product_id: str
    quantity: int
    unit_price_cents: int
    line_total_cents: int


@dataclass(frozen=True, slots=True)
class Payment:
    payment_id: str
    order_id: str
    amount_cents: int
    status: str


@dataclass(frozen=True, slots=True)
class Return:
    return_id: str
    order_id: str
    line_id: str
    quantity: int
    refund_cents: int


@dataclass(frozen=True, slots=True)
class InventoryMovement:
    movement_id: str
    product_id: str
    store_id: str
    quantity_delta: int
    reason: str
    movement_ts: int


@dataclass(frozen=True, slots=True)
class ProductVersion:
    product_id: str
    category: str
    effective_from: int
    effective_to: int | None
    loaded_at: int


@dataclass(frozen=True, slots=True)
class RetailBatch:
    orders: tuple[Order, ...]
    order_lines: tuple[OrderLine, ...]
    payments: tuple[Payment, ...]
    returns: tuple[Return, ...]
    inventory_movements: tuple[InventoryMovement, ...]
    products: tuple[ProductVersion, ...]

    def tables(self) -> dict[str, list[dict[str, Any]]]:
        return {
            "orders": [asdict(value) for value in self.orders],
            "order_lines": [asdict(value) for value in self.order_lines],
            "payments": [asdict(value) for value in self.payments],
            "returns": [asdict(value) for value in self.returns],
            "inventory_movements": [asdict(value) for value in self.inventory_movements],
            "products": [asdict(value) for value in self.products],
        }

    def row_count(self) -> int:
        return sum(len(rows) for rows in self.tables().values())
