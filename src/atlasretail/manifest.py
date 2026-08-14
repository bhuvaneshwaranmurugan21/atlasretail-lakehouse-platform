"""Versioned batch manifests bind declared inputs to exact payloads."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from .canonical import digest
from .errors import ManifestError
from .model import RetailBatch

SUPPORTED_CONTRACT = "retail-v1"


@dataclass(frozen=True, slots=True)
class TableProof:
    rows: int
    sha256: str


@dataclass(frozen=True, slots=True)
class BatchManifest:
    batch_id: str
    contract_version: str
    produced_at: int
    as_of_knowledge_time: int
    tables: dict[str, TableProof]

    @property
    def identity_digest(self) -> str:
        return digest(
            {
                "batch_id": self.batch_id,
                "contract_version": self.contract_version,
                "produced_at": self.produced_at,
                "as_of_knowledge_time": self.as_of_knowledge_time,
                "tables": {name: asdict(proof) for name, proof in sorted(self.tables.items())},
            }
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "batch_id": self.batch_id,
            "contract_version": self.contract_version,
            "produced_at": self.produced_at,
            "as_of_knowledge_time": self.as_of_knowledge_time,
            "tables": {name: asdict(proof) for name, proof in sorted(self.tables.items())},
            "identity_digest": self.identity_digest,
        }


def build_manifest(
    batch: RetailBatch,
    *,
    batch_id: str,
    produced_at: int,
    as_of_knowledge_time: int,
) -> BatchManifest:
    tables = batch.tables()
    return BatchManifest(
        batch_id=batch_id,
        contract_version=SUPPORTED_CONTRACT,
        produced_at=produced_at,
        as_of_knowledge_time=as_of_knowledge_time,
        tables={
            name: TableProof(rows=len(rows), sha256=digest(rows)) for name, rows in tables.items()
        },
    )


def verify_manifest(manifest: BatchManifest, batch: RetailBatch) -> None:
    if manifest.contract_version != SUPPORTED_CONTRACT:
        raise ManifestError(f"unsupported contract: {manifest.contract_version}")
    tables = batch.tables()
    if set(tables) != set(manifest.tables):
        raise ManifestError("manifest table set does not match payload")
    for name, rows in tables.items():
        proof = manifest.tables[name]
        if proof.rows != len(rows):
            raise ManifestError(f"row count mismatch for {name}")
        if proof.sha256 != digest(rows):
            raise ManifestError(f"digest mismatch for {name}")
