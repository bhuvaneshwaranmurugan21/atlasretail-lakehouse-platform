"""DynamoDB control plane for immutable identity and conditional publication."""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
from typing import Any
from urllib.parse import urlparse

import boto3
from botocore.exceptions import ClientError

TABLE_NAME = os.environ["CONTROL_TABLE"]
TABLE = boto3.resource("dynamodb").Table(TABLE_NAME)
EXPECTED_TABLES = {
    "orders",
    "order_lines",
    "payments",
    "returns",
    "inventory_movements",
    "products",
}


def _pointer_version() -> int:
    response = TABLE.get_item(Key={"pk": "CONTROL", "sk": "ACTIVE"}, ConsistentRead=True)
    item = response.get("Item")
    return int(item["pointer_version"]) if item else 0


def _generation_id(batch_id: str, manifest_digest: str) -> str:
    safe_batch = re.sub(r"[^A-Za-z0-9_-]", "-", batch_id).strip("-")[:64] or "batch"
    identity = hashlib.sha256(f"{batch_id}:{manifest_digest}".encode()).hexdigest()[:12]
    return f"g-{safe_batch}-{identity}"


def _generation(generation_id: str) -> dict[str, Any]:
    response = TABLE.get_item(
        Key={"pk": f"GENERATION#{generation_id}", "sk": "STATE"},
        ConsistentRead=True,
    )
    item = response.get("Item")
    if not item:
        raise ValueError(f"UNKNOWN_GENERATION: {generation_id}")
    return dict(item)


def _attribute(value: Any) -> dict[str, Any]:
    if isinstance(value, bool):
        return {"BOOL": value}
    if isinstance(value, int):
        return {"N": str(value)}
    return {"S": str(value)}


def _register(event: dict[str, Any]) -> dict[str, Any]:
    batch_id = str(event["batch_id"])
    manifest_digest = str(event["manifest_digest"])
    manifest_uri = str(event["manifest_uri"])
    manifest_version_id = str(event["manifest_version_id"])
    source_commit = str(event.get("source_commit", "unknown"))
    workflow_run_id = str(event.get("workflow_run_id", "unknown"))
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", batch_id):
        raise ValueError("batch_id is outside the contract")
    if not re.fullmatch(r"[a-f0-9]{64}", manifest_digest):
        raise ValueError("manifest_digest must be a SHA-256 hex digest")
    if not manifest_uri.startswith("s3://") or not manifest_version_id:
        raise ValueError("manifest must reference an exact S3 object version")

    batch_key = {"pk": f"BATCH#{batch_id}", "sk": "IDENTITY"}
    existing = TABLE.get_item(Key=batch_key, ConsistentRead=True).get("Item")
    if existing:
        if existing["manifest_digest"] != manifest_digest:
            raise ValueError(f"CONFLICT: batch {batch_id} was reused with different content")
        if (
            existing["manifest_uri"] != manifest_uri
            or existing["manifest_version_id"] != manifest_version_id
        ):
            raise ValueError(f"CONFLICT: batch {batch_id} manifest location changed")
        generation = _generation(str(existing["generation_id"]))
        status = str(generation["status"])
        classification = {
            "PUBLISHED": "REPLAYED",
            "FAILED": "RECOVERING",
        }.get(status, "IN_PROGRESS")
        return {
            "status": classification,
            "generation_id": existing["generation_id"],
            "generation_status": status,
            "pointer_version": _pointer_version(),
        }

    generation_id = _generation_id(batch_id, manifest_digest)
    now = int(time.time())
    batch_item = {
        **batch_key,
        "batch_id": batch_id,
        "generation_id": generation_id,
        "manifest_digest": manifest_digest,
        "manifest_uri": manifest_uri,
        "manifest_version_id": manifest_version_id,
        "registered_at": now,
        "source_commit": source_commit,
        "workflow_run_id": workflow_run_id,
    }
    generation_item = {
        "pk": f"GENERATION#{generation_id}",
        "sk": "STATE",
        "generation_id": generation_id,
        "batch_id": batch_id,
        "manifest_digest": manifest_digest,
        "status": "REGISTERED",
        "attempt": 0,
        "registered_at": now,
        "source_commit": source_commit,
        "workflow_run_id": workflow_run_id,
    }
    try:
        TABLE.meta.client.transact_write_items(
            TransactItems=[
                {
                    "Put": {
                        "TableName": TABLE_NAME,
                        "Item": {key: _attribute(value) for key, value in batch_item.items()},
                        "ConditionExpression": "attribute_not_exists(pk)",
                    }
                },
                {
                    "Put": {
                        "TableName": TABLE_NAME,
                        "Item": {key: _attribute(value) for key, value in generation_item.items()},
                        "ConditionExpression": "attribute_not_exists(pk)",
                    }
                },
            ]
        )
    except ClientError as error:
        if error.response["Error"]["Code"] not in {
            "ConditionalCheckFailedException",
            "TransactionCanceledException",
        }:
            raise
        return _register(event)
    return {
        "status": "REGISTERED",
        "generation_id": generation_id,
        "generation_status": "REGISTERED",
        "pointer_version": _pointer_version(),
    }


def _transition(
    generation_id: str,
    *,
    allowed: tuple[str, ...],
    target: str,
    extra: dict[str, Any] | None = None,
    increment_attempt: bool = False,
) -> dict[str, Any]:
    current = _generation(generation_id)
    if current["status"] not in allowed:
        raise ValueError(f"ILLEGAL_TRANSITION: {current['status']} -> {target} for {generation_id}")
    values: dict[str, Any] = {
        ":target": target,
        ":updated": int(time.time()),
        ":current": current["status"],
    }
    names = {"#status": "status"}
    assignments = ["#status = :target", "updated_at = :updated"]
    if increment_attempt:
        values[":one"] = 1
        values[":zero"] = 0
        assignments.append("attempt = if_not_exists(attempt, :zero) + :one")
    for index, (key, value) in enumerate((extra or {}).items()):
        name_token = f"#extra{index}"
        value_token = f":extra{index}"
        names[name_token] = key
        values[value_token] = value
        assignments.append(f"{name_token} = {value_token}")
    try:
        response = TABLE.update_item(
            Key={"pk": f"GENERATION#{generation_id}", "sk": "STATE"},
            UpdateExpression="SET " + ", ".join(assignments),
            ConditionExpression="#status = :current",
            ExpressionAttributeNames=names,
            ExpressionAttributeValues=values,
            ReturnValues="ALL_NEW",
        )
    except ClientError as error:
        if error.response["Error"]["Code"] == "ConditionalCheckFailedException":
            raise ValueError(f"CONCURRENT_TRANSITION: {generation_id}") from error
        raise
    return dict(response["Attributes"])


def _start_build(event: dict[str, Any]) -> dict[str, Any]:
    generation_id = str(event["generation_id"])
    state = _transition(
        generation_id,
        allowed=("REGISTERED", "FAILED"),
        target="BUILDING",
        extra={"execution_arn": str(event.get("execution_arn", "unknown"))},
        increment_attempt=True,
    )
    return {
        "status": "BUILDING",
        "generation_id": generation_id,
        "attempt": int(state["attempt"]),
    }


def _load_validation(uri: str) -> dict[str, Any]:
    parsed = urlparse(uri)
    if parsed.scheme != "s3" or not parsed.netloc or not parsed.path:
        raise ValueError("VALIDATION_EVIDENCE: invalid S3 URI")
    response = boto3.client("s3").get_object(Bucket=parsed.netloc, Key=parsed.path.lstrip("/"))
    return json.loads(response["Body"].read())


def _validate_generation(event: dict[str, Any]) -> dict[str, Any]:
    generation_id = str(event["generation_id"])
    evidence_uri = str(event["validation_uri"])
    evidence = _load_validation(evidence_uri)
    generation = _generation(generation_id)
    if evidence.get("generation_id") != generation_id:
        raise ValueError("VALIDATION_EVIDENCE: generation mismatch")
    if evidence.get("manifest_digest") != generation["manifest_digest"]:
        raise ValueError("VALIDATION_EVIDENCE: manifest mismatch")
    tables = evidence.get("tables", {})
    if set(tables) != EXPECTED_TABLES:
        raise ValueError("VALIDATION_EVIDENCE: six-table snapshot set is incomplete")
    for name, snapshot in tables.items():
        if int(snapshot.get("snapshot_id", 0)) <= 0 or int(snapshot.get("rows", -1)) < 0:
            raise ValueError(f"VALIDATION_EVIDENCE: invalid snapshot for {name}")
    glue_job_run_id = str(event.get("glue_job_run_id", ""))
    if evidence.get("scope") != "CONTROL_PLANE_CAS_ONLY" and not glue_job_run_id:
        raise ValueError("VALIDATION_EVIDENCE: Glue job run identity is absent")
    digest = hashlib.sha256(
        json.dumps(evidence, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    _transition(
        generation_id,
        allowed=("BUILDING",),
        target="VALIDATED",
        extra={
            "validation_uri": evidence_uri,
            "validation_digest": digest,
            "glue_job_run_id": glue_job_run_id or "CONTROL_PLANE_CAS_ONLY",
        },
    )
    return {
        "status": "VALIDATED",
        "generation_id": generation_id,
        "validation_digest": digest,
    }


def _publish(event: dict[str, Any]) -> dict[str, Any]:
    generation_id = str(event["generation_id"])
    expected = int(event["expected_pointer_version"])
    generation = _generation(generation_id)
    if generation["status"] != "VALIDATED":
        raise ValueError("NOT_VALIDATED: only a validated generation can publish")
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
                            "pk": {"S": f"GENERATION#{generation_id}"},
                            "sk": {"S": "STATE"},
                        },
                        "UpdateExpression": (
                            "SET #status = :published, published_at = :published_at"
                        ),
                        "ConditionExpression": "#status = :validated",
                        "ExpressionAttributeNames": {"#status": "status"},
                        "ExpressionAttributeValues": {
                            ":published": {"S": "PUBLISHED"},
                            ":validated": {"S": "VALIDATED"},
                            ":published_at": {"N": str(now)},
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


def _fail(event: dict[str, Any]) -> dict[str, Any]:
    generation_id = str(event["generation_id"])
    current = _generation(generation_id)
    if current["status"] == "PUBLISHED":
        raise ValueError("ILLEGAL_TRANSITION: published generation cannot fail")
    state = _transition(
        generation_id,
        allowed=("REGISTERED", "BUILDING", "VALIDATED"),
        target="FAILED",
        extra={
            "failure_stage": str(event.get("failure_stage", "UNKNOWN"))[:64],
            "failure_code": str(event.get("failure_code", "UNKNOWN"))[:512],
        },
    )
    return {"status": state["status"], "generation_id": generation_id}


def _resolve() -> dict[str, Any]:
    response = TABLE.get_item(Key={"pk": "CONTROL", "sk": "ACTIVE"}, ConsistentRead=True)
    pointer = response.get("Item")
    if not pointer:
        raise ValueError("NO_ACTIVE_GENERATION")
    generation_id = str(pointer["active_generation"])
    generation = _generation(generation_id)
    if generation["status"] != "PUBLISHED":
        raise ValueError("ACTIVE_POINTER_INVALID")
    return {
        "status": "RESOLVED",
        "generation_id": generation_id,
        "pointer_version": int(pointer["pointer_version"]),
        "validation_digest": generation["validation_digest"],
    }


def handler(event: dict[str, Any], _context: object) -> dict[str, Any]:
    action = event.get("action")
    if action == "register":
        return _register(event)
    if action == "start_build":
        return _start_build(event)
    if action == "validate":
        return _validate_generation(event)
    if action == "publish":
        return _publish(event)
    if action == "fail":
        return _fail(event)
    if action == "resolve":
        return _resolve()
    raise ValueError(f"unsupported action: {action}")
