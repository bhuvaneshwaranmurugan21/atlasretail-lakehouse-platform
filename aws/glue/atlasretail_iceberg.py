"""AWS Glue 5 job: verify immutable inputs and build one isolated Iceberg generation."""

from __future__ import annotations

import base64
import gzip
import hashlib
import json
import sys
from collections.abc import Iterable, Iterator
from contextlib import closing
from typing import TYPE_CHECKING, Any, BinaryIO
from urllib.parse import urlparse

if TYPE_CHECKING:
    from pyspark.sql import DataFrame, SparkSession

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
    return frame.groupBy(*columns).count().filter("count > 1").limit(1).count()


def parse_s3_uri(uri: str) -> tuple[str, str]:
    value = urlparse(uri)
    if value.scheme != "s3" or not value.netloc or not value.path:
        fail("S3_URI", uri)
    return value.netloc, value.path.lstrip("/")


def canonical_digest(value: dict[str, object]) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def canonical_table_digest(streams: Iterable[BinaryIO]) -> tuple[int, str]:
    """Verify the existing ordered-row contract without collecting a table in memory."""
    hasher = hashlib.sha256()
    hasher.update(b"[")
    rows = 0
    for stream in streams:
        with gzip.GzipFile(fileobj=stream, mode="rb") as compressed:
            for line in compressed:
                record = json.loads(line)
                if not isinstance(record, dict):
                    fail("OBJECT_CONTENT", "registered record is not a JSON object")
                if rows:
                    hasher.update(b",")
                hasher.update(
                    json.dumps(record, sort_keys=True, separators=(",", ":")).encode("utf-8")
                )
                rows += 1
    hasher.update(b"]")
    return rows, hasher.hexdigest()


def object_payloads(s3: Any, objects: list[dict[str, Any]]) -> Iterator[BinaryIO]:
    """Stream only the manifest-registered immutable object versions."""
    for proof in objects:
        response = s3.get_object(
            Bucket=str(proof["bucket"]),
            Key=str(proof["key"]),
            VersionId=str(proof["version_id"]),
        )
        with closing(response["Body"]) as body:
            yield body


def verify_table_digest(
    s3: Any,
    *,
    table: str,
    proof: dict[str, Any],
) -> None:
    """Bind exact S3 bytes to the manifest's independently declared row proof."""
    try:
        actual_rows, actual_digest = canonical_table_digest(object_payloads(s3, proof["objects"]))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError) as error:
        fail("OBJECT_CONTENT", f"{table}: unreadable registered NDJSON: {error}")
    expected_rows = int(proof["rows"])
    if actual_rows != expected_rows:
        fail("ROW_COUNT", f"{table}: expected={expected_rows}, actual={actual_rows}")
    if actual_digest != str(proof["sha256"]):
        fail("TABLE_DIGEST", f"{table}: canonical record digest differs from the manifest")


def load_registered_frames(
    spark: SparkSession,
    s3: Any,
    *,
    args: dict[str, str],
    manifest: dict[str, Any],
    manifest_bucket: str,
) -> dict[str, DataFrame]:
    """Verify object and logical-row identity before Spark observes any input."""
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

        verify_table_digest(s3, table=table, proof=proof)
        frame = spark.read.json(verified_uris)
        expected = int(proof["rows"])
        actual = frame.count()
        if actual != expected:
            fail("ROW_COUNT", f"{table}: expected={expected}, actual={actual}")
        frames[table] = frame
    return frames


def validate_frames(frames: dict[str, DataFrame], *, knowledge_time: int) -> None:
    """Apply the same business invariants as the dependency-free correctness kernel."""
    from pyspark.sql import Window
    from pyspark.sql import functions as F

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
        lines.filter(
            F.col("quantity").isNull()
            | F.col("unit_price_cents").isNull()
            | (F.col("quantity") <= 0)
            | (F.col("unit_price_cents") < 0)
        )
        .limit(1)
        .count()
    ):
        fail("INVALID_LINE", "quantity must be positive and unit price must be non-negative")
    if (
        lines.filter(F.col("line_total_cents") != F.col("quantity") * F.col("unit_price_cents"))
        .limit(1)
        .count()
    ):
        fail("LINE_TOTAL", "quantity * unit price mismatch")
    if (
        orders.filter(F.col("currency").isNull() | ~F.col("currency").isin("INR", "USD"))
        .limit(1)
        .count()
    ):
        fail("CURRENCY", "unsupported order currency")
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

    if (
        returns.join(lines.select("order_id", "line_id"), ["order_id", "line_id"], "left_anti")
        .limit(1)
        .count()
    ):
        fail("ORPHAN_RETURN", "order line is missing")
    if (
        returns.filter(
            F.col("quantity").isNull()
            | F.col("refund_cents").isNull()
            | (F.col("quantity") <= 0)
            | (F.col("refund_cents") < 0)
        )
        .limit(1)
        .count()
    ):
        fail("INVALID_RETURN", "quantity must be positive and refund must be non-negative")

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
        & (F.col("product.loaded_at") <= F.lit(knowledge_time)),
        "left",
    )
    temporal_counts = temporal_matches.groupBy("line.order_id", "line.line_id").agg(
        F.count("product.product_id").alias("dimension_matches")
    )
    if temporal_counts.filter(F.col("dimension_matches") == 0).limit(1).count():
        fail("MISSING_DIMENSION", "no knowable product version at order time")
    if temporal_counts.filter(F.col("dimension_matches") > 1).limit(1).count():
        fail("AMBIGUOUS_DIMENSION", "multiple product versions overlap at order time")


def write_generation(
    spark: SparkSession,
    frames: dict[str, DataFrame],
    *,
    database: str,
    generation_id: str,
) -> dict[str, dict[str, int]]:
    """Build or deterministically replace one generation in six Iceberg tables."""
    from pyspark.sql import functions as F

    snapshot_evidence: dict[str, dict[str, int]] = {}
    for table, frame in frames.items():
        enriched = frame.withColumn("generation_id", F.lit(generation_id))
        identifier = f"glue_catalog.{database}.{table}"
        if not spark.catalog.tableExists(identifier):
            (
                enriched.writeTo(identifier)
                .using("iceberg")
                .tableProperty("format-version", "2")
                .tableProperty("write.format.default", "parquet")
                .create()
            )
        else:
            safe_generation = generation_id.replace("'", "''")
            spark.sql(f"DELETE FROM {identifier} WHERE generation_id = '{safe_generation}'")
            enriched.writeTo(identifier).append()
        snapshot_id = int(
            spark.sql(
                f"SELECT snapshot_id FROM {identifier}.snapshots ORDER BY committed_at DESC LIMIT 1"
            ).first()["snapshot_id"]
        )
        snapshot_evidence[table] = {"snapshot_id": snapshot_id, "rows": frame.count()}
    return snapshot_evidence


def build_generation(
    spark: SparkSession,
    frames: dict[str, DataFrame],
    *,
    database: str,
    generation_id: str,
    knowledge_time: int,
    inject_failure: bool = False,
) -> dict[str, dict[str, int]]:
    """Validate before writes and support a fail-before-publication recovery proof."""
    validate_frames(frames, knowledge_time=knowledge_time)
    evidence = write_generation(
        spark,
        frames,
        database=database,
        generation_id=generation_id,
    )
    if inject_failure:
        raise RuntimeError("INJECTED_FAILURE: physical snapshots written; publication blocked")
    return evidence


def main() -> None:
    import boto3
    from awsglue.context import GlueContext
    from awsglue.job import Job
    from awsglue.utils import getResolvedOptions
    from pyspark.context import SparkContext

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

    frames = load_registered_frames(
        spark,
        s3,
        args=args,
        manifest=manifest,
        manifest_bucket=manifest_bucket,
    )
    snapshot_evidence = build_generation(
        spark,
        frames,
        database=args["DATABASE"],
        generation_id=args["GENERATION_ID"],
        knowledge_time=int(manifest["as_of_knowledge_time"]),
        inject_failure=args["INJECT_FAILURE"].lower() == "true",
    )

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


if __name__ == "__main__":
    main()
