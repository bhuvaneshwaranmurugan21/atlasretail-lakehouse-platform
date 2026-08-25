"""Canonical serialization and digest helpers."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from typing import Any


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def digest(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def digest_records(records: Iterable[Any]) -> tuple[int, str]:
    """Hash a canonical JSON array incrementally without materializing its records."""
    hasher = hashlib.sha256()
    hasher.update(b"[")
    count = 0
    for record in records:
        if count:
            hasher.update(b",")
        hasher.update(canonical_json(record).encode("utf-8"))
        count += 1
    hasher.update(b"]")
    return count, hasher.hexdigest()
