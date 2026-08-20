"""Deterministic synthetic retail workload generation."""

from __future__ import annotations

import random
from dataclasses import replace

from .model import InventoryMovement, Order, OrderLine, Payment, ProductVersion, RetailBatch, Return


def generate_batch(
    *, order_count: int = 50, seed: int = 21, start_ts: int = 1_700_000_000
) -> RetailBatch:
    if order_count < 1:
        raise ValueError("order_count must be positive")
    rng = random.Random(seed)
    products = tuple(
        ProductVersion(
            product_id=f"p-{index:03d}",
            category=("grocery", "home", "electronics")[index % 3],
            effective_from=start_ts - 86_400,
            effective_to=None,
            loaded_at=start_ts - 3_600,
        )
        for index in range(1, 21)
    )

    orders: list[Order] = []
    lines: list[OrderLine] = []
    payments: list[Payment] = []
    returns: list[Return] = []
    inventory: list[InventoryMovement] = []

    for product in products:
        for store_id in ("s-01", "s-02", "s-03"):
            inventory.append(
                InventoryMovement(
                    movement_id=f"opening-{product.product_id}-{store_id}",
                    product_id=product.product_id,
                    store_id=store_id,
                    quantity_delta=max(100, order_count * 4),
                    reason="OPENING",
                    movement_ts=start_ts - 1,
                )
            )

    for order_index in range(order_count):
        order_id = f"o-{order_index:08d}"
        store_id = f"s-{(order_index % 3) + 1:02d}"
        order_ts = start_ts + order_index * 10
        line_count = 1 + rng.randrange(3)
        order_lines: list[OrderLine] = []
        for line_index in range(line_count):
            product = products[(order_index * 3 + line_index) % len(products)]
            quantity = 1 + rng.randrange(3)
            unit_price = 1000 + ((order_index + line_index) % 50) * 37
            line = OrderLine(
                order_id=order_id,
                line_id=f"l-{line_index + 1}",
                product_id=product.product_id,
                quantity=quantity,
                unit_price_cents=unit_price,
                line_total_cents=quantity * unit_price,
            )
            order_lines.append(line)
            inventory.append(
                InventoryMovement(
                    movement_id=f"sale-{order_id}-{line.line_id}",
                    product_id=product.product_id,
                    store_id=store_id,
                    quantity_delta=-quantity,
                    reason="SALE",
                    movement_ts=order_ts,
                )
            )
        subtotal = sum(line.line_total_cents for line in order_lines)
        discount = 100 if order_index % 10 == 0 else 0
        tax = subtotal * 18 // 100
        total = subtotal + tax - discount
        orders.append(
            Order(
                order_id=order_id,
                customer_id=f"c-{order_index % max(5, order_count // 5):05d}",
                store_id=store_id,
                order_ts=order_ts,
                status="COMPLETED",
                subtotal_cents=subtotal,
                tax_cents=tax,
                discount_cents=discount,
                total_cents=total,
                currency="INR",
            )
        )
        lines.extend(order_lines)
        payments.append(
            Payment(
                payment_id=f"pay-{order_index:08d}",
                order_id=order_id,
                amount_cents=total,
                status="CAPTURED",
            )
        )
        if order_index % 17 == 0:
            returned_line = order_lines[0]
            returns.append(
                Return(
                    return_id=f"ret-{order_index:08d}",
                    order_id=order_id,
                    line_id=returned_line.line_id,
                    quantity=1,
                    refund_cents=returned_line.unit_price_cents,
                )
            )
            inventory.append(
                InventoryMovement(
                    movement_id=f"return-{order_id}-{returned_line.line_id}",
                    product_id=returned_line.product_id,
                    store_id=store_id,
                    quantity_delta=1,
                    reason="RETURN",
                    movement_ts=order_ts + 5,
                )
            )

    return RetailBatch(
        orders=tuple(orders),
        order_lines=tuple(lines),
        payments=tuple(payments),
        returns=tuple(returns),
        inventory_movements=tuple(inventory),
        products=products,
    )


def with_broken_total(batch: RetailBatch) -> RetailBatch:
    first = batch.orders[0]
    return replace(
        batch, orders=(replace(first, total_cents=first.total_cents + 1), *batch.orders[1:])
    )


def with_excess_refund(batch: RetailBatch) -> RetailBatch:
    first_order = batch.orders[0]
    first_line = next(line for line in batch.order_lines if line.order_id == first_order.order_id)
    bad_return = Return(
        return_id="ret-excess",
        order_id=first_order.order_id,
        line_id=first_line.line_id,
        quantity=1,
        refund_cents=first_order.total_cents + 1,
    )
    return replace(batch, returns=(*batch.returns, bad_return))


def with_missing_dimension(batch: RetailBatch) -> RetailBatch:
    product_id = batch.order_lines[0].product_id
    return replace(
        batch, products=tuple(value for value in batch.products if value.product_id != product_id)
    )


def with_overlapping_dimension(batch: RetailBatch) -> RetailBatch:
    first = batch.products[0]
    overlap = replace(
        first,
        category="overlapping-version",
        effective_from=first.effective_from + 1,
        loaded_at=first.loaded_at + 1,
    )
    return replace(batch, products=(*batch.products, overlap))


def with_negative_inventory(batch: RetailBatch) -> RetailBatch:
    line = batch.order_lines[0]
    order = batch.orders[0]
    bad = InventoryMovement(
        movement_id="negative-stock",
        product_id=line.product_id,
        store_id=order.store_id,
        quantity_delta=-1_000_000,
        reason="CORRUPTION",
        movement_ts=order.order_ts + 1,
    )
    return replace(batch, inventory_movements=(*batch.inventory_movements, bad))
