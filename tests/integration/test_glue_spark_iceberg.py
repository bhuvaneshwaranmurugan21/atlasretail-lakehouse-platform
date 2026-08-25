from __future__ import annotations

import importlib.util
import json
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("pyspark")

from pyspark.sql import DataFrame, SparkSession  # noqa: E402
from pyspark.sql import functions as F  # noqa: E402

from atlasretail.generator import generate_batch  # noqa: E402
from atlasretail.model import RetailBatch  # noqa: E402

SCRIPT = Path(__file__).parents[2] / "aws" / "glue" / "atlasretail_iceberg.py"
SPEC = importlib.util.spec_from_file_location("atlasretail_iceberg_integration", SCRIPT)
assert SPEC and SPEC.loader
GLUE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(GLUE)
KNOWLEDGE_TIME = 1_700_100_000


@pytest.fixture(scope="module")
def spark(tmp_path_factory: pytest.TempPathFactory) -> Any:
    warehouse = tmp_path_factory.mktemp("atlas-iceberg-warehouse")
    session = (
        SparkSession.builder.master("local[2]")
        .appName("atlasretail-glue-5-correctness")
        .config("spark.ui.enabled", "false")
        .config("spark.sql.shuffle.partitions", "2")
        .config("spark.default.parallelism", "2")
        .config(
            "spark.sql.extensions",
            "org.apache.iceberg.spark.extensions.IcebergSparkSessionExtensions",
        )
        .config("spark.sql.catalog.glue_catalog", "org.apache.iceberg.spark.SparkCatalog")
        .config("spark.sql.catalog.glue_catalog.type", "hadoop")
        .config("spark.sql.catalog.glue_catalog.warehouse", str(warehouse))
        .getOrCreate()
    )
    session.sparkContext.setLogLevel("ERROR")
    yield session
    session.stop()


@pytest.fixture(scope="module")
def batch() -> RetailBatch:
    return generate_batch(order_count=3, seed=21)


@pytest.fixture(scope="module")
def frames(spark: SparkSession, batch: RetailBatch) -> dict[str, DataFrame]:
    result: dict[str, DataFrame] = {}
    for table, rows in batch.tables().items():
        encoded = [json.dumps(row, sort_keys=True) for row in rows]
        frame = spark.read.json(spark.sparkContext.parallelize(encoded, 1)).cache()
        frame.count()
        result[table] = frame
    yield result
    for frame in result.values():
        frame.unpersist()


@pytest.mark.parametrize(
    ("table", "column", "value", "code"),
    [
        ("orders", "currency", "EUR", "CURRENCY"),
        ("order_lines", "quantity", 0, "INVALID_LINE"),
        ("returns", "quantity", 0, "INVALID_RETURN"),
        ("returns", "line_id", "missing-line", "ORPHAN_RETURN"),
        ("orders", "total_cents", -1, "ORDER_TOTAL"),
    ],
)
def test_spark_business_rules_match_the_local_kernel(
    frames: dict[str, DataFrame],
    table: str,
    column: str,
    value: str | int,
    code: str,
) -> None:
    changed = dict(frames)
    changed[table] = frames[table].withColumn(column, F.lit(value))
    with pytest.raises(ValueError, match=f"QUALITY_GATE:{code}:"):
        GLUE.validate_frames(changed, knowledge_time=KNOWLEDGE_TIME)


def test_same_timestamp_inventory_uses_deterministic_identity_order(
    spark: SparkSession,
    frames: dict[str, DataFrame],
    batch: RetailBatch,
) -> None:
    movement = batch.inventory_movements[0]
    debit = replace(movement, movement_id="a-debit", quantity_delta=-1)
    credit = replace(movement, movement_id="z-credit", quantity_delta=1)
    records = [
        {
            "movement_id": value.movement_id,
            "product_id": value.product_id,
            "store_id": value.store_id,
            "quantity_delta": value.quantity_delta,
            "reason": value.reason,
            "movement_ts": value.movement_ts,
        }
        for value in (credit, debit)
    ]
    encoded = [json.dumps(record) for record in records]
    changed = dict(frames)
    changed["inventory_movements"] = spark.read.json(spark.sparkContext.parallelize(encoded, 1))
    with pytest.raises(ValueError, match="QUALITY_GATE:NEGATIVE_INVENTORY:"):
        GLUE.validate_frames(changed, knowledge_time=KNOWLEDGE_TIME)


def test_real_iceberg_snapshots_replay_and_failure_recovery(
    spark: SparkSession,
    frames: dict[str, DataFrame],
) -> None:
    database = "atlasretail_integration"
    spark.sql(f"CREATE NAMESPACE IF NOT EXISTS glue_catalog.{database}")

    first = GLUE.build_generation(
        spark,
        frames,
        database=database,
        generation_id="generation-success",
        knowledge_time=KNOWLEDGE_TIME,
    )
    assert set(first) == set(GLUE.TABLES)
    assert all(value["snapshot_id"] > 0 for value in first.values())

    replay = GLUE.build_generation(
        spark,
        frames,
        database=database,
        generation_id="generation-success",
        knowledge_time=KNOWLEDGE_TIME,
    )
    assert {table: value["rows"] for table, value in replay.items()} == {
        table: value["rows"] for table, value in first.items()
    }
    for table, value in first.items():
        query = (
            f"SELECT COUNT(*) AS rows FROM glue_catalog.{database}.{table} "
            "WHERE generation_id = 'generation-success'"
        )
        assert spark.sql(query).first()["rows"] == value["rows"]

    with pytest.raises(RuntimeError, match="INJECTED_FAILURE"):
        GLUE.build_generation(
            spark,
            frames,
            database=database,
            generation_id="generation-recovery",
            knowledge_time=KNOWLEDGE_TIME,
            inject_failure=True,
        )

    recovered = GLUE.build_generation(
        spark,
        frames,
        database=database,
        generation_id="generation-recovery",
        knowledge_time=KNOWLEDGE_TIME,
    )
    assert set(recovered) == set(GLUE.TABLES)
    for table, value in recovered.items():
        query = (
            f"SELECT COUNT(*) AS rows FROM glue_catalog.{database}.{table} "
            "WHERE generation_id = 'generation-recovery'"
        )
        assert spark.sql(query).first()["rows"] == value["rows"]
