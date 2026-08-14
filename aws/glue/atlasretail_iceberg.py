"""AWS Glue 5 job: validate a retail batch and build an isolated Iceberg generation."""

from __future__ import annotations

import json
import sys
from urllib.parse import urlparse

import boto3
from awsglue.context import GlueContext
from awsglue.job import Job
from awsglue.utils import getResolvedOptions
from pyspark.context import SparkContext
from pyspark.sql import DataFrame, Window
from pyspark.sql import functions as F

TABLES = (
    "orders",
    "order_lines",
    "payments",
    "returns",
    "inventory_movements",
    "products",
)


def fail(code: str, detail: str) -> None:
    raise ValueError(f"QUALITY_GATE:{code}:{detail}")


def duplicates(frame: DataFrame, columns: list[str]) -> int:
    return frame.groupBy(*columns).count().filter(F.col("count") > 1).limit(1).count()


args = getResolvedOptions(
    sys.argv,
    [
        "JOB_NAME",
        "SOURCE_URI",
        "MANIFEST_URI",
        "BATCH_ID",
        "GENERATION_ID",
        "DATABASE",
        "INJECT_FAILURE",
    ],
)

glue_context = GlueContext(SparkContext.getOrCreate())
spark = glue_context.spark_session
job = Job(glue_context)
job.init(args["JOB_NAME"], args)

manifest_url = urlparse(args["MANIFEST_URI"])
manifest = json.loads(
    boto3.client("s3")
    .get_object(Bucket=manifest_url.netloc, Key=manifest_url.path.lstrip("/"))["Body"]
    .read()
)
if manifest["batch_id"] != args["BATCH_ID"] or manifest["contract_version"] != "retail-v1":
    fail("MANIFEST_IDENTITY", "batch ID or contract version mismatch")

frames: dict[str, DataFrame] = {}
for table in TABLES:
    frame = spark.read.json(f"{args['SOURCE_URI'].rstrip('/')}/{table}/*.jsonl.gz")
    expected = int(manifest["tables"][table]["rows"])
    actual = frame.count()
    if actual != expected:
        fail("ROW_COUNT", f"{table}: expected={expected}, actual={actual}")
    frames[table] = frame

identity_keys = {
    "orders": ["order_id"],
    "order_lines": ["order_id", "line_id"],
    "payments": ["payment_id"],
    "returns": ["return_id"],
    "inventory_movements": ["movement_id"],
    "products": ["product_id", "effective_from", "loaded_at"],
}
for table, keys in identity_keys.items():
    if duplicates(frames[table], keys):
        fail("DUPLICATE_ID", table)

orders = frames["orders"]
lines = frames["order_lines"]
payments = frames["payments"]
returns = frames["returns"]
inventory = frames["inventory_movements"]
products = frames["products"]

if (
    lines.filter(F.col("line_total_cents") != F.col("quantity") * F.col("unit_price_cents"))
    .limit(1)
    .count()
):
    fail("LINE_TOTAL", "quantity * unit price mismatch")
if (
    orders.filter(
        F.col("total_cents")
        != F.col("subtotal_cents") + F.col("tax_cents") - F.col("discount_cents")
    )
    .limit(1)
    .count()
):
    fail("ORDER_TOTAL", "financial equation mismatch")

line_totals = lines.groupBy("order_id").agg(F.sum("line_total_cents").alias("line_subtotal"))
if (
    orders.join(line_totals, "order_id", "left")
    .filter(F.coalesce(F.col("line_subtotal"), F.lit(0)) != F.col("subtotal_cents"))
    .limit(1)
    .count()
):
    fail("ORDER_SUBTOTAL", "line sum mismatch")

captured = (
    payments.filter(F.col("status") == "CAPTURED")
    .groupBy("order_id")
    .agg(F.sum("amount_cents").alias("captured_cents"))
)
if (
    orders.filter(F.col("status") == "COMPLETED")
    .join(captured, "order_id", "left")
    .filter(F.coalesce(F.col("captured_cents"), F.lit(0)) < F.col("total_cents"))
    .limit(1)
    .count()
):
    fail("UNDERPAID", "captured payment is below completed order total")

refunds = returns.groupBy("order_id").agg(F.sum("refund_cents").alias("refund_cents"))
if (
    refunds.join(captured, "order_id", "left")
    .filter(F.col("refund_cents") > F.coalesce(F.col("captured_cents"), F.lit(0)))
    .limit(1)
    .count()
):
    fail("EXCESS_REFUND", "refund exceeds capture")

returned_quantity = returns.groupBy("order_id", "line_id").agg(
    F.sum("quantity").alias("returned_quantity")
)
if (
    returned_quantity.join(lines, ["order_id", "line_id"], "left")
    .filter(F.col("quantity").isNull() | (F.col("returned_quantity") > F.col("quantity")))
    .limit(1)
    .count()
):
    fail("RETURN_QUANTITY", "return exceeds order line")

stock_window = (
    Window.partitionBy("product_id", "store_id")
    .orderBy("movement_ts", "movement_id")
    .rowsBetween(Window.unboundedPreceding, Window.currentRow)
)
if (
    inventory.withColumn("stock", F.sum("quantity_delta").over(stock_window))
    .filter(F.col("stock") < 0)
    .limit(1)
    .count()
):
    fail("NEGATIVE_INVENTORY", "cumulative stock below zero")

temporal_match = (
    lines.join(orders.select("order_id", "order_ts"), "order_id")
    .alias("line")
    .join(
        products.alias("product"),
        (F.col("line.product_id") == F.col("product.product_id"))
        & (F.col("product.effective_from") <= F.col("line.order_ts"))
        & (
            F.col("product.effective_to").isNull()
            | (F.col("line.order_ts") < F.col("product.effective_to"))
        )
        & (F.col("product.loaded_at") <= F.lit(int(manifest["as_of_knowledge_time"]))),
        "left",
    )
)
if temporal_match.filter(F.col("product.product_id").isNull()).limit(1).count():
    fail("MISSING_DIMENSION", "no knowable product version at order time")

for table, frame in frames.items():
    enriched = frame.withColumn("generation_id", F.lit(args["GENERATION_ID"]))
    identifier = f"glue_catalog.{args['DATABASE']}.{table}"
    if not spark.catalog.tableExists(identifier):
        (
            enriched.writeTo(identifier)
            .using("iceberg")
            .tableProperty("format-version", "2")
            .tableProperty("write.format.default", "parquet")
            .create()
        )
    else:
        spark.sql(f"DELETE FROM {identifier} WHERE generation_id = '{args['GENERATION_ID']}'")
        enriched.writeTo(identifier).append()

if args["INJECT_FAILURE"].lower() == "true":
    raise RuntimeError("INJECTED_FAILURE: generation written but publication deliberately blocked")

job.commit()
