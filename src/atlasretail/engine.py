from __future__ import annotations

from dataclasses import replace
from typing import Iterable

from .model import Batch, RetailEvent, Snapshot, digest


class ContractViolation(ValueError):
    """An event violates the versioned retail contract."""


class ReplayConflict(ValueError):
    """An identity was reused with different content."""


class PublicationConflict(ValueError):
    """The active-snapshot pointer changed concurrently."""


class InjectedFailure(RuntimeError):
    """A deterministic failure used to prove atomicity."""


class RetailLakehouse:
    """Transport-neutral oracle for atomic retail lakehouse publication."""

    def __init__(self) -> None:
        self.event_digests: dict[str, str] = {}
        self.batch_digests: dict[str, str] = {}
        self.orders: dict[str, int] = {}
        self.refunds: dict[str, int] = {}
        self.inventory: dict[str, int] = {}
        self.snapshots: list[Snapshot] = []
        self.active_snapshot_id: str | None = None
        self.pointer_version = 0

    def apply_batch(self, batch: Batch, *, fail_before_commit: bool = False) -> str:
        known_batch = self.batch_digests.get(batch.batch_id)
        if known_batch is not None:
            if known_batch != batch.payload_digest:
                raise ReplayConflict(f"batch {batch.batch_id} changed payload")
            return "replayed"

        event_digests = self.event_digests.copy()
        orders = self.orders.copy()
        refunds = self.refunds.copy()
        inventory = self.inventory.copy()

        for event in batch.events:
            self._validate_contract(event)
            known_event = event_digests.get(event.event_id)
            if known_event is not None:
                if known_event != event.payload_digest:
                    raise ReplayConflict(f"event {event.event_id} changed payload")
                continue
            self._apply(event, orders, refunds, inventory)
            event_digests[event.event_id] = event.payload_digest

        if fail_before_commit:
            raise InjectedFailure("failure before atomic snapshot commit")

        snapshot = self._snapshot(batch.batch_id, event_digests, orders, refunds, inventory)
        self.event_digests = event_digests
        self.orders = orders
        self.refunds = refunds
        self.inventory = inventory
        self.batch_digests[batch.batch_id] = batch.payload_digest
        self.snapshots.append(snapshot)
        return "applied"

    def publish_latest(self, *, expected_pointer_version: int) -> Snapshot:
        if expected_pointer_version != self.pointer_version:
            raise PublicationConflict(
                f"expected pointer {expected_pointer_version}, current {self.pointer_version}"
            )
        if not self.snapshots:
            raise ContractViolation("no candidate snapshot")
        candidate = self.snapshots[-1]
        self._validate_totals()
        published = replace(candidate, published=True)
        self.snapshots[-1] = published
        self.active_snapshot_id = published.snapshot_id
        self.pointer_version += 1
        return published

    def build_backfill(self, batch_id: str, events: Iterable[RetailEvent]) -> Snapshot:
        before = self.active_snapshot_id
        self.apply_batch(Batch(batch_id, tuple(events)))
        assert self.active_snapshot_id == before
        return self.snapshots[-1]

    def _validate_contract(self, event: RetailEvent) -> None:
        if event.schema_version != 1:
            raise ContractViolation(f"unsupported schema version {event.schema_version}")
        if not event.event_id or not event.business_id:
            raise ContractViolation("event and business identities are required")
        if event.knowledge_time < event.event_time:
            raise ContractViolation("knowledge time cannot precede event time")

    def _apply(
        self,
        event: RetailEvent,
        orders: dict[str, int],
        refunds: dict[str, int],
        inventory: dict[str, int],
    ) -> None:
        if event.kind == "order":
            if event.amount_cents <= 0:
                raise ContractViolation("order amount must be positive")
            existing = orders.get(event.business_id)
            if existing is not None and existing != event.amount_cents:
                raise ReplayConflict(f"order {event.business_id} changed total")
            orders[event.business_id] = event.amount_cents
        elif event.kind == "return":
            order_total = orders.get(event.business_id)
            if order_total is None:
                raise ContractViolation("return references unknown order")
            if event.amount_cents <= 0:
                raise ContractViolation("return amount must be positive")
            new_total = refunds.get(event.business_id, 0) + event.amount_cents
            if new_total > order_total:
                raise ContractViolation("refund exceeds captured order amount")
            refunds[event.business_id] = new_total
        elif event.kind == "inventory":
            new_units = inventory.get(event.business_id, 0) + event.quantity
            if new_units < 0:
                raise ContractViolation("inventory cannot become negative")
            inventory[event.business_id] = new_units
        else:  # pragma: no cover - Literal prevents this in typed code
            raise ContractViolation(f"unknown event kind {event.kind}")

    def _snapshot(
        self,
        batch_id: str,
        event_digests: dict[str, str],
        orders: dict[str, int],
        refunds: dict[str, int],
        inventory: dict[str, int],
    ) -> Snapshot:
        state = {
            "events": sorted(event_digests.items()),
            "orders": sorted(orders.items()),
            "refunds": sorted(refunds.items()),
            "inventory": sorted(inventory.items()),
        }
        state_digest = digest(state)
        return Snapshot(
            snapshot_id=f"snap-{len(self.snapshots) + 1}-{state_digest[:12]}",
            batch_id=batch_id,
            row_count=len(event_digests),
            order_cents=sum(orders.values()),
            refund_cents=sum(refunds.values()),
            inventory_units=sum(inventory.values()),
            state_digest=state_digest,
        )

    def _validate_totals(self) -> None:
        for order_id, refund in self.refunds.items():
            if refund > self.orders[order_id]:
                raise ContractViolation(f"refund exceeds order {order_id}")

