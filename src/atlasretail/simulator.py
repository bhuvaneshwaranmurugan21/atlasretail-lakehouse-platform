"""Deterministic local failure lab."""

from __future__ import annotations

import json
import tempfile
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from typing import Any

from .canonical import digest
from .engine import AtlasEngine
from .errors import ConflictError, ManifestError, PublicationError, QualityGateError
from .generator import (
    generate_batch,
    with_broken_total,
    with_excess_refund,
    with_missing_dimension,
    with_negative_inventory,
)
from .manifest import TableProof, build_manifest


def _expected_failure(error: type[Exception], action: Callable[[], object]) -> str:
    try:
        action()
    except error as caught:
        return str(caught)
    raise AssertionError(f"expected {error.__name__}")


def run_failure_lab() -> dict[str, Any]:
    checks: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix="atlasretail-") as temporary:
        root = Path(temporary)
        engine = AtlasEngine(root)
        batch = generate_batch(order_count=30, seed=21)
        manifest = build_manifest(
            batch,
            batch_id="base-001",
            produced_at=1_700_001_000,
            as_of_knowledge_time=1_700_001_000,
        )
        built = engine.build_generation(manifest, batch)
        checks.append({"check": "retail_invariants", "passed": True, "proof": built.metrics})

        version = engine.publish(built.generation_id, expected_pointer_version=0)
        checks.append(
            {
                "check": "atomic_publication",
                "passed": engine.pointer() == (built.generation_id, version),
                "proof": version,
            }
        )

        replayed = engine.build_generation(manifest, batch)
        checks.append(
            {
                "check": "idempotent_batch_replay",
                "passed": replayed.status == "replayed"
                and replayed.snapshot_digest == built.snapshot_digest,
                "proof": replayed.snapshot_digest,
            }
        )

        altered = replace(manifest, produced_at=manifest.produced_at + 1)
        conflict = _expected_failure(ConflictError, lambda: engine.build_generation(altered, batch))
        checks.append({"check": "conflicting_batch_identity", "passed": True, "proof": conflict})

        tampered_tables = dict(manifest.tables)
        original = tampered_tables["orders"]
        tampered_tables["orders"] = TableProof(rows=original.rows + 1, sha256=original.sha256)
        tampered = replace(manifest, batch_id="tampered-001", tables=tampered_tables)
        manifest_error = _expected_failure(
            ManifestError, lambda: engine.build_generation(tampered, batch)
        )
        checks.append({"check": "manifest_row_count", "passed": True, "proof": manifest_error})

        scenarios = [
            ("financial_equation_gate", with_broken_total(batch), "ORDER_TOTAL"),
            ("excess_refund_gate", with_excess_refund(batch), "EXCESS_REFUND"),
            ("negative_inventory_gate", with_negative_inventory(batch), "NEGATIVE_INVENTORY"),
            ("late_dimension_gate", with_missing_dimension(batch), "MISSING_DIMENSION"),
        ]
        for index, (name, invalid, expected_code) in enumerate(scenarios, start=1):
            invalid_manifest = build_manifest(
                invalid,
                batch_id=f"invalid-{index}",
                produced_at=1_700_002_000 + index,
                as_of_knowledge_time=1_700_002_000 + index,
            )
            proof = _expected_failure(
                QualityGateError,
                lambda invalid_manifest=invalid_manifest, invalid=invalid: engine.build_generation(
                    invalid_manifest, invalid
                ),
            )
            checks.append({"check": name, "passed": expected_code in proof, "proof": proof})

        crash_manifest = build_manifest(
            batch,
            batch_id="crash-001",
            produced_at=1_700_003_000,
            as_of_knowledge_time=1_700_003_000,
        )
        before = engine.pointer()
        crash = _expected_failure(
            RuntimeError,
            lambda: engine.build_generation(crash_manifest, batch, inject_failure=True),
        )
        after = engine.pointer()
        checks.append(
            {
                "check": "atomic_failure_rollback",
                "passed": before == after and not (engine.snapshots / "g-crash-001.json").exists(),
                "proof": crash,
            }
        )

        recovered = engine.build_generation(crash_manifest, batch)
        checks.append(
            {
                "check": "deterministic_recovery",
                "passed": recovered.status == "built",
                "proof": recovered.snapshot_digest,
            }
        )

        stale = _expected_failure(
            PublicationError,
            lambda: engine.publish(recovered.generation_id, expected_pointer_version=0),
        )
        checks.append({"check": "stale_publication_blocked", "passed": True, "proof": stale})

        pointer_before_backfill = engine.pointer()
        backfill = generate_batch(order_count=10, seed=84, start_ts=1_699_000_000)
        backfill_manifest = build_manifest(
            backfill,
            batch_id="backfill-001",
            produced_at=1_700_004_000,
            as_of_knowledge_time=1_700_004_000,
        )
        backfill_result = engine.build_generation(backfill_manifest, backfill)
        checks.append(
            {
                "check": "backfill_generation_isolation",
                "passed": engine.pointer() == pointer_before_backfill,
                "proof": backfill_result.generation_id,
            }
        )

        engine.assert_consistent()
        checks.append(
            {
                "check": "snapshot_digest_integrity",
                "passed": True,
                "proof": "all snapshots verified",
            }
        )

    passed = all(check["passed"] for check in checks)
    evidence = {
        "project": "atlasretail-lakehouse-platform",
        "architecture": "iceberg-snapshot-publication",
        "claim_level": "LOCAL_VERIFIED",
        "production_claim": False,
        "result": "PASS" if passed else "FAIL",
        "checks": checks,
        "metrics": {
            "checks_total": len(checks),
            "checks_passed": sum(bool(check["passed"]) for check in checks),
        },
    }
    evidence["evidence_digest"] = digest(evidence)
    return evidence


def write_evidence(path: Path) -> dict[str, Any]:
    evidence = run_failure_lab()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return evidence
