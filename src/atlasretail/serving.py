"""Consumer boundary for resolving one published generation across all retail tables."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

TABLES = (
    "orders",
    "order_lines",
    "payments",
    "returns",
    "inventory_movements",
    "products",
)


@dataclass(frozen=True, slots=True)
class ServingResolution:
    generation_id: str
    pointer_version: int
    validation_digest: str

    @classmethod
    def from_control_response(cls, value: dict[str, Any]) -> ServingResolution:
        if value.get("status") != "RESOLVED":
            raise ValueError("control response does not contain a published generation")
        resolution = cls(
            generation_id=str(value["generation_id"]),
            pointer_version=int(value["pointer_version"]),
            validation_digest=str(value["validation_digest"]),
        )
        if resolution.pointer_version < 1 or not re.fullmatch(
            r"g-[A-Za-z0-9_-]+-[a-f0-9]{12}", resolution.generation_id
        ):
            raise ValueError("serving pointer identity is invalid")
        if not re.fullmatch(r"[a-f0-9]{64}", resolution.validation_digest):
            raise ValueError("serving validation digest is invalid")
        return resolution


def six_table_count_query(database: str, resolution: ServingResolution) -> str:
    """Build one diagnostic query after resolving the pointer exactly once."""
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", database):
        raise ValueError("database identifier is invalid")
    generation = resolution.generation_id
    projections = [
        (f"(SELECT count(*) FROM {database}.{table} WHERE generation_id='{generation}') AS {table}")
        for table in TABLES
    ]
    return "SELECT\n  " + ",\n  ".join(projections)
