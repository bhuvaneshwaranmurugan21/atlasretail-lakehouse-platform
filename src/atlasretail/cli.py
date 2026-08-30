"""Command line interface for deterministic proof and data generation."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .provenance import generate_source_data, materialize_part4_sources, validate_order_count
from .serving import ServingResolution, six_table_count_query
from .simulator import write_evidence


def _generate(output: Path, *, orders: int, seed: int, batch_id: str, fault: str) -> None:
    generate_source_data(
        output,
        orders=orders,
        seed=seed,
        batch_id=batch_id,
        fault=fault,
    )


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(prog="atlasretail")
    commands = root.add_subparsers(dest="command", required=True)
    simulate = commands.add_parser("simulate", help="run the deterministic local failure lab")
    simulate.add_argument("--output", type=Path, required=True)
    generate = commands.add_parser("generate", help="generate deterministic gzipped NDJSON inputs")
    generate.add_argument("--output", type=Path, required=True)
    generate.add_argument("--orders", type=int, default=500)
    generate.add_argument("--seed", type=int, default=21)
    generate.add_argument("--batch-id", default="aws-lab-001")
    generate.add_argument(
        "--fault",
        choices=("none", "financial", "temporal-overlap"),
        default="none",
    )
    sources = commands.add_parser(
        "generate-sources", help="materialize all contract-bound Part 4 source families"
    )
    sources.add_argument("--output", type=Path, required=True)
    sources.add_argument("--orders", type=int, default=500)
    sources.add_argument("--source-commit", required=True)
    sources.add_argument("--run-id", required=True)
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
        validate_order_count(arguments.orders)
        _generate(
            arguments.output,
            orders=arguments.orders,
            seed=arguments.seed,
            batch_id=arguments.batch_id,
            fault=arguments.fault,
        )
        print(json.dumps({"result": "PASS", "output": str(arguments.output)}))
    elif arguments.command == "generate-sources":
        summary = materialize_part4_sources(
            arguments.output,
            repo_root=Path.cwd(),
            order_count=arguments.orders,
            source_commit=arguments.source_commit,
            run_id=arguments.run_id,
        )
        print(json.dumps(summary, sort_keys=True))
    elif arguments.command == "serving-query":
        resolution = ServingResolution.from_control_response(
            json.loads(arguments.resolution.read_text(encoding="utf-8"))
        )
        print(six_table_count_query(arguments.database, resolution))


if __name__ == "__main__":
    main()
