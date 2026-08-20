"""AWS Glue 5 job: verify immutable inputs and build one isolated Iceberg generation."""

from __future__ import annotations

import base64
import hashlib
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


def parse_s3_uri(uri: str) -> tuple[str, str]:
    value = urlparse(uri)
    if value.scheme != "s3" or not value.netloc or not value.path:
        fail("S3_URI", uri)
    return value.netloc, value.path.lstrip("/")


def canonical_digest(value: dict[str, object]) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


args = getResolvedOptions(
    sys.argv,
    [
        "JOB_NAME",
        "MANIFEST_URI",
        "MANIFEST_VERSION_ID",
        "MANIFEST_DIGEST",
        "BATCH_ID",
        "GENERATION_ID",
        "DATABASE",
        "VALIDATION_URI",
        "INJECT_FAILURE",
    ],
)

glue_context = GlueContext(SparkContext.getOrCreate())
spark = glue_context.spark_session
job = Job(glue_context)
job.init(args["JOB_NAME"], args)
s3 = boto3.client("s3")

manifest_bucket, manifest_key = parse_s3_uri(args["MANIFEST_URI"])
manifest_response = s3.get_object(
    Bucket=manifest_bucket,
    Key=manifest_key,
    VersionId=args["MANIFEST_VERSION_ID"],
)
manifest = json.loads(manifest_response["Body"].read())
supplied_digest = manifest.pop("identity_digest", None)
computed_digest = canonical_digest(manifest)
if supplied_digest != computed_digest or computed_digest != args["MANIFEST_DIGEST"]:
    fail("MANIFEST_DIGEST", "canonical manifest identity mismatch")
if manifest["batch_id"] != args["BATCH_ID"] or manifest["contract_version"] != "retail-v2":
    fail("MANIFEST_IDENTITY", "batch ID or contract version mismatch")
if set(manifest.get("tables", {})) != set(TABLES):
    fail("MANIFEST_TABLE_SET", "exactly six registered tables are required")

frames: dict[str, DataFrame] = {}
for table in TABLES:
    proof = manifest["tables"][table]
    objects = proof.get("objects", [])
    if not objects:
        fail("OBJECT_IDENTITY", f"{table}: no registered objects")
    verified_uris: list[str] = []
    for index, object_proof in enumerate(objects):
        bucket = str(object_proof["bucket"])
        key = str(object_proof["key"])
        version_id = str(object_proof["version_id"])
        head = s3.head_object(
            Bucket=bucket,
            Key=key,
            VersionId=version_id,
            ChecksumMode="ENABLED",
        )
        checksum = head.get("ChecksumSHA256")
        if checksum is None:
            fail("OBJECT_CHECKSUM", f"{table}: S3 checksum is absent")
        checksum_hex = base64.b64decode(checksum).hex()
        if (
            int(head["ContentLength"]) != int(object_proof["size_bytes"])
            or checksum_hex != object_proof["sha256"]
            or str(head["ETag"]).strip('"') != str(object_proof["etag"]).strip('"')
        ):
            fail("OBJECT_IDENTITY", f"{table}: registered object evidence changed")

        verified_key = f"verified/{args['GENERATION_ID']}/{table}/{index}.jsonl.gz"
        s3.copy_object(
            Bucket=manifest_bucket,
            Key=verified_key,
            CopySource={"Bucket": bucket, "Key": key, "VersionId": version_id},
            CopySourceIfMatch=str(head["ETag"]),
            ChecksumAlgorithm="SHA256",
        )
        verified_uris.append(f"s3://{manifest_bucket}/{verified_key}")

    frame = spark.read.json(verified_uris)
    expected = int(proof["rows"])
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

if lines.join(orders.select("order_id"), "order_id", "left_anti").limit(1).count():
    fail("ORPHAN_LINE", "order is missing")
if payments.join(orders.select("order_id"), "order_id", "left_anti").limit(1).count():
    fail("ORPHAN_PAYMENT", "order is missing")
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

line_events = lines.select("order_id", "line_id", "product_id").join(
    orders.select("order_id", "order_ts"), "order_id"
)
temporal_matches = line_events.alias("line").join(
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
temporal_counts = temporal_matches.groupBy("line.order_id", "line.line_id").agg(
    F.count("product.product_id").alias("dimension_matches")
)
if temporal_counts.filter(F.col("dimension_matches") == 0).limit(1).count():
    fail("MISSING_DIMENSION", "no knowable product version at order time")
if temporal_counts.filter(F.col("dimension_matches") > 1).limit(1).count():
    fail("AMBIGUOUS_DIMENSION", "multiple product versions overlap at order time")

snapshot_evidence: dict[str, dict[str, int]] = {}
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
        safe_generation = args["GENERATION_ID"].replace("'", "''")
        spark.sql(f"DELETE FROM {identifier} WHERE generation_id = '{safe_generation}'")
        enriched.writeTo(identifier).append()
    snapshot_id = int(
        spark.sql(
            f"SELECT snapshot_id FROM {identifier}.snapshots ORDER BY committed_at DESC LIMIT 1"
        ).first()["snapshot_id"]
    )
    snapshot_evidence[table] = {"snapshot_id": snapshot_id, "rows": frame.count()}

if args["INJECT_FAILURE"].lower() == "true":
    raise RuntimeError("INJECTED_FAILURE: physical snapshots written; publication blocked")

validation_bucket, validation_key = parse_s3_uri(args["VALIDATION_URI"])
validation = {
    "batch_id": args["BATCH_ID"],
    "generation_id": args["GENERATION_ID"],
    "manifest_digest": args["MANIFEST_DIGEST"],
    "tables": snapshot_evidence,
}
s3.put_object(
    Bucket=validation_bucket,
    Key=validation_key,
    Body=(json.dumps(validation, sort_keys=True, separators=(",", ":")) + "\n").encode(),
    ContentType="application/json",
    ChecksumAlgorithm="SHA256",
)
job.commit()
