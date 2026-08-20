"""Versioned batch manifests bind declared inputs to exact payloads."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, replace
from typing import Any

from .canonical import digest
from .errors import ManifestError
from .model import RetailBatch

SUPPORTED_CONTRACT = "retail-v2"


@dataclass(frozen=True, slots=True)
class ObjectProof:
    bucket: str
    key: str
    version_id: str
    size_bytes: int
    sha256: str
    etag: str


@dataclass(frozen=True, slots=True)
class TableProof:
    rows: int
    sha256: str
    objects: tuple[ObjectProof, ...] = field(default_factory=tuple)


@dataclass(frozen=True, slots=True)
class BatchManifest:
    batch_id: str
    contract_version: str
    produced_at: int
    as_of_knowledge_time: int
    tables: dict[str, TableProof]

    @property
    def identity_digest(self) -> str:
        return digest(self.identity_payload())

    def identity_payload(self) -> dict[str, Any]:
        return {
            "batch_id": self.batch_id,
            "contract_version": self.contract_version,
            "produced_at": self.produced_at,
            "as_of_knowledge_time": self.as_of_knowledge_time,
            "tables": {name: asdict(proof) for name, proof in sorted(self.tables.items())},
        }

    def to_dict(self) -> dict[str, Any]:
        return {**self.identity_payload(), "identity_digest": self.identity_digest}


def bind_objects(
    manifest: BatchManifest,
    objects: dict[str, tuple[ObjectProof, ...]],
) -> BatchManifest:
    """Return an immutable managed manifest bound to exact S3 object versions."""
    if set(objects) != set(manifest.tables):
        raise ManifestError("object table set does not match manifest")
    tables: dict[str, TableProof] = {}
    for name, proof in manifest.tables.items():
        table_objects = objects[name]
        if not table_objects:
            raise ManifestError(f"no objects registered for {name}")
        tables[name] = replace(proof, objects=table_objects)
    return replace(manifest, tables=tables)


def manifest_from_dict(value: dict[str, Any]) -> BatchManifest:
    tables = {
        name: TableProof(
            rows=int(proof["rows"]),
            sha256=str(proof["sha256"]),
            objects=tuple(ObjectProof(**item) for item in proof.get("objects", [])),
        )
        for name, proof in value["tables"].items()
    }
    manifest = BatchManifest(
        batch_id=str(value["batch_id"]),
        contract_version=str(value["contract_version"]),
        produced_at=int(value["produced_at"]),
        as_of_knowledge_time=int(value["as_of_knowledge_time"]),
        tables=tables,
    )
    supplied_digest = value.get("identity_digest")
    if supplied_digest is not None and supplied_digest != manifest.identity_digest:
        raise ManifestError("manifest identity digest does not match canonical content")
    return manifest


def verify_managed_manifest(manifest: BatchManifest) -> None:
    if manifest.contract_version != SUPPORTED_CONTRACT:
        raise ManifestError(f"unsupported contract: {manifest.contract_version}")
    for name, proof in manifest.tables.items():
        if not proof.objects:
            raise ManifestError(f"table {name} is not bound to an object")
        for item in proof.objects:
            if not item.bucket or not item.key or not item.version_id:
                raise ManifestError(f"table {name} has incomplete S3 identity")
            if item.size_bytes < 1 or len(item.sha256) != 64:
                raise ManifestError(f"table {name} has invalid object evidence")


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
