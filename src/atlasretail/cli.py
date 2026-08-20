"""Command line interface for deterministic proof and data generation."""

from __future__ import annotations

import argparse
import gzip
import json
from pathlib import Path
from typing import Any

from .generator import generate_batch, with_broken_total, with_overlapping_dimension
from .manifest import build_manifest
from .serving import ServingResolution, six_table_count_query
from .simulator import write_evidence


def _write_ndjson_gzip(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt", encoding="utf-8") as stream:
        for row in rows:
            stream.write(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n")


def _generate(output: Path, *, orders: int, seed: int, batch_id: str, fault: str) -> None:
    batch = generate_batch(order_count=orders, seed=seed)
    if fault == "financial":
        batch = with_broken_total(batch)
    elif fault == "temporal-overlap":
        batch = with_overlapping_dimension(batch)
    manifest = build_manifest(
        batch,
        batch_id=batch_id,
        produced_at=1_700_100_000,
        as_of_knowledge_time=1_700_100_000,
    )
    for table, rows in batch.tables().items():
        _write_ndjson_gzip(output / table / f"{batch_id}.jsonl.gz", rows)
    (output / "manifest.json").write_text(
        json.dumps(manifest.to_dict(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (output / "expected-results.json").write_text(
        json.dumps(
            {
                "gross_cents": sum(order.total_cents for order in batch.orders),
                "orders": len(batch.orders),
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(prog="atlasretail")
    commands = root.add_subparsers(dest="command", required=True)
    simulate = commands.add_parser("simulate", help="run the deterministic local failure lab")
    simulate.add_argument("--output", type=Path, required=True)
    generate = commands.add_parser("generate", help="generate deterministic gzipped NDJSON inputs")
    generate.add_argument("--output", type=Path, required=True)
    generate.add_argument("--orders", type=int, default=10_000)
    generate.add_argument("--seed", type=int, default=21)
    generate.add_argument("--batch-id", default="aws-lab-001")
    generate.add_argument(
        "--fault",
        choices=("none", "financial", "temporal-overlap"),
        default="none",
    )
    serving = commands.add_parser(
        "serving-query", help="build a six-table query from one resolved generation"
    )
    serving.add_argument("--resolution", type=Path, required=True)
    serving.add_argument("--database", required=True)
    return root


def main() -> None:
    arguments = parser().parse_args()
    if arguments.command == "simulate":
        evidence = write_evidence(arguments.output)
        print(json.dumps({"result": evidence["result"], "output": str(arguments.output)}))
        if evidence["result"] != "PASS":
            raise SystemExit(1)
    elif arguments.command == "generate":
        _generate(
            arguments.output,
            orders=arguments.orders,
            seed=arguments.seed,
            batch_id=arguments.batch_id,
            fault=arguments.fault,
        )
        print(json.dumps({"result": "PASS", "output": str(arguments.output)}))
    elif arguments.command == "serving-query":
        resolution = ServingResolution.from_control_response(
            json.loads(arguments.resolution.read_text(encoding="utf-8"))
        )
        print(six_table_count_query(arguments.database, resolution))


if __name__ == "__main__":
    main()
