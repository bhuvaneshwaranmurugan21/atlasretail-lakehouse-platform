"""DynamoDB control plane for idempotent registration and conditional publication."""

from __future__ import annotations

import os
import re
import time
from typing import Any

import boto3
from botocore.exceptions import ClientError

TABLE_NAME = os.environ["CONTROL_TABLE"]
TABLE = boto3.resource("dynamodb").Table(TABLE_NAME)


def _pointer_version() -> int:
    response = TABLE.get_item(
        Key={"pk": "CONTROL", "sk": "ACTIVE"},
        ConsistentRead=True,
    )
    item = response.get("Item")
    return int(item["pointer_version"]) if item else 0


def _register(event: dict[str, Any]) -> dict[str, Any]:
    batch_id = str(event["batch_id"])
    generation_id = str(event["generation_id"])
    manifest_digest = str(event["manifest_digest"])
    if not re.fullmatch(r"[a-f0-9]{64}", manifest_digest):
        raise ValueError("manifest_digest must be a SHA-256 hex digest")

    key = {"pk": f"BATCH#{batch_id}", "sk": "IDENTITY"}
    existing = TABLE.get_item(Key=key, ConsistentRead=True).get("Item")
    if existing:
        if existing["manifest_digest"] != manifest_digest:
            raise ValueError(f"CONFLICT: batch {batch_id} was reused with different content")
        status = "REPLAYED" if existing["status"] == "PUBLISHED" else "RECOVERING"
        return {
            "status": status,
            "generation_id": existing["generation_id"],
            "pointer_version": _pointer_version(),
        }

    item = {
        **key,
        "batch_id": batch_id,
        "generation_id": generation_id,
        "manifest_digest": manifest_digest,
        "status": "REGISTERED",
        "registered_at": int(time.time()),
    }
    try:
        TABLE.put_item(Item=item, ConditionExpression="attribute_not_exists(pk)")
    except ClientError as error:
        if error.response["Error"]["Code"] != "ConditionalCheckFailedException":
            raise
        return _register(event)
    return {
        "status": "REGISTERED",
        "generation_id": generation_id,
        "pointer_version": _pointer_version(),
    }


def _publish(event: dict[str, Any]) -> dict[str, Any]:
    batch_id = str(event["batch_id"])
    generation_id = str(event["generation_id"])
    expected = int(event["expected_pointer_version"])
    now = int(time.time())
    try:
        TABLE.meta.client.transact_write_items(
            TransactItems=[
                {
                    "Update": {
                        "TableName": TABLE_NAME,
                        "Key": {"pk": {"S": "CONTROL"}, "sk": {"S": "ACTIVE"}},
                        "UpdateExpression": (
                            "SET active_generation = :generation, pointer_version = :next, "
                            "published_at = :published_at"
                        ),
                        "ConditionExpression": (
                            "(attribute_not_exists(pointer_version) AND :expected = :zero) "
                            "OR pointer_version = :expected"
                        ),
                        "ExpressionAttributeValues": {
                            ":generation": {"S": generation_id},
                            ":expected": {"N": str(expected)},
                            ":zero": {"N": "0"},
                            ":next": {"N": str(expected + 1)},
                            ":published_at": {"N": str(now)},
                        },
                    }
                },
                {
                    "Update": {
                        "TableName": TABLE_NAME,
                        "Key": {
                            "pk": {"S": f"BATCH#{batch_id}"},
                            "sk": {"S": "IDENTITY"},
                        },
                        "UpdateExpression": (
                            "SET #status = :published, published_at = :published_at"
                        ),
                        "ConditionExpression": "generation_id = :generation",
                        "ExpressionAttributeNames": {"#status": "status"},
                        "ExpressionAttributeValues": {
                            ":published": {"S": "PUBLISHED"},
                            ":published_at": {"N": str(now)},
                            ":generation": {"S": generation_id},
                        },
                    }
                },
            ]
        )
    except ClientError as error:
        if error.response["Error"]["Code"] in {
            "ConditionalCheckFailedException",
            "TransactionCanceledException",
        }:
            raise ValueError("STALE_PUBLISHER: active generation changed during build") from error
        raise
    return {
        "status": "PUBLISHED",
        "generation_id": generation_id,
        "pointer_version": expected + 1,
    }


def handler(event: dict[str, Any], _context: object) -> dict[str, Any]:
    action = event.get("action")
    if action == "register":
        return _register(event)
    if action == "publish":
        return _publish(event)
    raise ValueError(f"unsupported action: {action}")
