import pytest

from atlasretail.engine import ContractViolation, InjectedFailure, PublicationConflict, ReplayConflict
from atlasretail.model import Batch, RetailEvent
from atlasretail import RetailLakehouse


def event(event_id: str, kind: str, key: str, amount: int = 0, quantity: int = 0) -> RetailEvent:
    return RetailEvent(event_id, kind, key, 1, 1, amount, quantity)  # type: ignore[arg-type]


def test_atomic_apply_replay_and_publication() -> None:
    lake = RetailLakehouse()
    batch = Batch("b1", (event("o1", "order", "order-1", amount=100),))
    assert lake.apply_batch(batch) == "applied"
    assert lake.apply_batch(batch) == "replayed"
    assert lake.publish_latest(expected_pointer_version=0).published
    with pytest.raises(PublicationConflict):
        lake.publish_latest(expected_pointer_version=0)


def test_conflicts_and_financial_invariant() -> None:
    lake = RetailLakehouse()
    lake.apply_batch(Batch("b1", (event("o1", "order", "order-1", amount=100),)))
    with pytest.raises(ReplayConflict):
        lake.apply_batch(Batch("b1", (event("o2", "order", "order-2", amount=100),)))
    with pytest.raises(ContractViolation):
        lake.apply_batch(Batch("b2", (event("r1", "return", "order-1", amount=101),)))


def test_failure_does_not_mutate_state() -> None:
    lake = RetailLakehouse()
    lake.apply_batch(Batch("b1", (event("s1", "inventory", "sku", quantity=5),)))
    before = lake.snapshots[-1]
    with pytest.raises(InjectedFailure):
        lake.apply_batch(
            Batch("b2", (event("s2", "inventory", "sku", quantity=-1),)),
            fail_before_commit=True,
        )
    assert lake.snapshots[-1] == before
    assert lake.inventory["sku"] == 5


def test_backfill_does_not_publish() -> None:
    lake = RetailLakehouse()
    lake.apply_batch(Batch("b1", (event("s1", "inventory", "sku", quantity=5),)))
    lake.publish_latest(expected_pointer_version=0)
    active = lake.active_snapshot_id
    lake.build_backfill("b2", (event("s2", "inventory", "sku", quantity=1),))
    assert lake.active_snapshot_id == active

