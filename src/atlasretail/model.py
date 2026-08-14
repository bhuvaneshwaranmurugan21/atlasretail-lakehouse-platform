from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha256
import json
from typing import Any, Literal

EventKind = Literal["order", "return", "inventory"]


def digest(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return sha256(encoded).hexdigest()


@dataclass(frozen=True, slots=True)
class RetailEvent:
    event_id: str
    kind: EventKind
    business_id: str
    event_time: int
    knowledge_time: int
    amount_cents: int = 0
    quantity: int = 0
    schema_version: int = 1

    @property
    def payload_digest(self) -> str:
        return digest(asdict(self))


@dataclass(frozen=True, slots=True)
class Batch:
    batch_id: str
    events: tuple[RetailEvent, ...]

    @property
    def payload_digest(self) -> str:
        return digest({"batch_id": self.batch_id, "events": [asdict(e) for e in self.events]})


@dataclass(frozen=True, slots=True)
class Snapshot:
    snapshot_id: str
    batch_id: str
    row_count: int
    order_cents: int
    refund_cents: int
    inventory_units: int
    state_digest: str
    published: bool = False

