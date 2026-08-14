"""Atomic generation build, publication, replay and rollback semantics."""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .canonical import digest
from .errors import ConflictError, PublicationError, QualityGateError
from .manifest import BatchManifest, verify_manifest
from .model import RetailBatch
from .quality import validate


@dataclass(frozen=True, slots=True)
class BuildResult:
    generation_id: str
    status: str
    snapshot_digest: str
    metrics: dict[str, int]


class AtlasEngine:
    """Small filesystem oracle mirroring generation-scoped Iceberg publication."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.snapshots = root / "snapshots"
        self.state_path = root / "state.json"
        self.snapshots.mkdir(parents=True, exist_ok=True)
        if not self.state_path.exists():
            self._write_state(
                {"manifests": {}, "generations": {}, "active": None, "pointer_version": 0}
            )

    def _state(self) -> dict[str, Any]:
        return json.loads(self.state_path.read_text(encoding="utf-8"))

    def _write_json_atomic(self, path: Path, value: Any) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                json.dump(value, stream, sort_keys=True, separators=(",", ":"))
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary_name, path)
        finally:
            temporary = Path(temporary_name)
            if temporary.exists():
                temporary.unlink()

    def _write_state(self, value: dict[str, Any]) -> None:
        self._write_json_atomic(self.state_path, value)

    def build_generation(
        self,
        manifest: BatchManifest,
        batch: RetailBatch,
        *,
        inject_failure: bool = False,
    ) -> BuildResult:
        verify_manifest(manifest, batch)
        state = self._state()
        existing = state["manifests"].get(manifest.batch_id)
        if existing is not None:
            if existing["manifest_digest"] != manifest.identity_digest:
                raise ConflictError(f"batch {manifest.batch_id} was reused with different content")
            generation = state["generations"][existing["generation_id"]]
            return BuildResult(
                generation_id=existing["generation_id"],
                status="replayed",
                snapshot_digest=generation["snapshot_digest"],
                metrics=generation["metrics"],
            )

        report = validate(batch, knowledge_time=manifest.as_of_knowledge_time)
        if not report.passed:
            codes = sorted({violation.code for violation in report.violations})
            raise QualityGateError(",".join(codes))

        generation_id = f"g-{manifest.batch_id}"
        payload = {
            "generation_id": generation_id,
            "manifest": manifest.to_dict(),
            "tables": batch.tables(),
            "metrics": report.metrics,
        }
        snapshot_digest = digest(payload)
        target = self.snapshots / f"{generation_id}.json"

        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{generation_id}.", dir=self.snapshots
        )
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                json.dump(payload, stream, sort_keys=True, separators=(",", ":"))
                stream.flush()
                os.fsync(stream.fileno())
            if inject_failure:
                raise RuntimeError("injected failure before snapshot commit")
            os.replace(temporary_name, target)
        finally:
            temporary = Path(temporary_name)
            if temporary.exists():
                temporary.unlink()

        state["generations"][generation_id] = {
            "status": "ready",
            "snapshot": str(target.relative_to(self.root)),
            "snapshot_digest": snapshot_digest,
            "metrics": report.metrics,
        }
        state["manifests"][manifest.batch_id] = {
            "manifest_digest": manifest.identity_digest,
            "generation_id": generation_id,
        }
        self._write_state(state)
        return BuildResult(generation_id, "built", snapshot_digest, report.metrics)

    def publish(self, generation_id: str, *, expected_pointer_version: int) -> int:
        state = self._state()
        generation = state["generations"].get(generation_id)
        if generation is None or generation["status"] != "ready":
            raise PublicationError("only a ready generation can be published")
        if state["pointer_version"] != expected_pointer_version:
            actual_pointer_version = state["pointer_version"]
            raise PublicationError(
                f"stale pointer version: expected {expected_pointer_version}, "
                f"actual {actual_pointer_version}"
            )
        previous = state["active"]
        state["active"] = generation_id
        state["pointer_version"] += 1
        generation["status"] = "active"
        if previous is not None and previous != generation_id:
            state["generations"][previous]["status"] = "retained"
        self._write_state(state)
        return int(state["pointer_version"])

    def pointer(self) -> tuple[str | None, int]:
        state = self._state()
        return state["active"], int(state["pointer_version"])

    def snapshot(self, generation_id: str) -> dict[str, Any]:
        state = self._state()
        generation = state["generations"].get(generation_id)
        if generation is None:
            raise KeyError(generation_id)
        return json.loads((self.root / generation["snapshot"]).read_text(encoding="utf-8"))

    def assert_consistent(self) -> None:
        state = self._state()
        for generation_id, metadata in state["generations"].items():
            payload = self.snapshot(generation_id)
            if digest(payload) != metadata["snapshot_digest"]:
                raise PublicationError(f"snapshot digest mismatch for {generation_id}")
        active = state["active"]
        if active is not None and active not in state["generations"]:
            raise PublicationError("active pointer references a missing generation")
