from __future__ import annotations

import importlib.util
import io
import json
import os
import sys
import types
import unittest
from pathlib import Path
from typing import Any


class FakeClientError(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.response = {"Error": {"Code": code}}


def decode(value: dict[str, Any]) -> Any:
    for name in ("S", "N", "BOOL"):
        if name in value:
            if name == "N":
                return int(value[name])
            return value[name]
    raise AssertionError(value)


class FakeTable:
    def __init__(self) -> None:
        self.items: dict[tuple[str, str], dict[str, Any]] = {}
        self.get_item_calls = 0
        self.transact_write_calls = 0
        self.last_transact_items: list[dict[str, Any]] = []
        self.registration_transaction_error: str | None = None
        self.commit_registration_before_error = False

    def reset(self) -> None:
        self.items.clear()
        self.get_item_calls = 0
        self.transact_write_calls = 0
        self.last_transact_items = []
        self.registration_transaction_error = None
        self.commit_registration_before_error = False

    def get_item(self, *, Key: dict[str, str], ConsistentRead: bool) -> dict[str, Any]:
        del ConsistentRead
        self.get_item_calls += 1
        item = self.items.get((Key["pk"], Key["sk"]))
        return {"Item": dict(item)} if item else {}

    def update_item(
        self,
        *,
        Key: dict[str, str],
        UpdateExpression: str,
        ConditionExpression: str,
        ExpressionAttributeNames: dict[str, str],
        ExpressionAttributeValues: dict[str, Any],
        ReturnValues: str,
    ) -> dict[str, Any]:
        del ConditionExpression, ReturnValues
        item = self.items[(Key["pk"], Key["sk"])]
        if item["status"] != ExpressionAttributeValues[":current"]:
            raise FakeClientError("ConditionalCheckFailedException")
        item["status"] = ExpressionAttributeValues[":target"]
        item["updated_at"] = ExpressionAttributeValues[":updated"]
        if "attempt =" in UpdateExpression:
            item["attempt"] = int(item.get("attempt", 0)) + 1
        for token, name in ExpressionAttributeNames.items():
            if not token.startswith("#extra"):
                continue
            index = token.removeprefix("#extra")
            item[name] = ExpressionAttributeValues[f":extra{index}"]
        return {"Attributes": dict(item)}

    def transact_write_items(self, *, TransactItems: list[dict[str, Any]]) -> None:
        self.transact_write_calls += 1
        self.last_transact_items = TransactItems
        if all("Put" in operation for operation in TransactItems):
            decoded = []
            for operation in TransactItems:
                item = {key: decode(value) for key, value in operation["Put"]["Item"].items()}
                key = (item["pk"], item["sk"])
                if key in self.items:
                    raise FakeClientError("TransactionCanceledException")
                decoded.append((key, item))
            if self.registration_transaction_error:
                if self.commit_registration_before_error:
                    self.items.update(decoded)
                raise FakeClientError(self.registration_transaction_error)
            self.items.update(decoded)
            return

        pointer_update, generation_update = (item["Update"] for item in TransactItems)
        pointer_values = pointer_update["ExpressionAttributeValues"]
        expected = int(pointer_values[":expected"]["N"])
        current_pointer = self.items.get(("CONTROL", "ACTIVE"))
        actual = int(current_pointer["pointer_version"]) if current_pointer else 0
        generation_key = (
            generation_update["Key"]["pk"]["S"],
            generation_update["Key"]["sk"]["S"],
        )
        generation = self.items[generation_key]
        if actual != expected or generation["status"] != "VALIDATED":
            raise FakeClientError("TransactionCanceledException")
        self.items[("CONTROL", "ACTIVE")] = {
            "pk": "CONTROL",
            "sk": "ACTIVE",
            "active_generation": pointer_values[":generation"]["S"],
            "pointer_version": int(pointer_values[":next"]["N"]),
            "published_at": int(pointer_values[":published_at"]["N"]),
        }
        generation["status"] = "PUBLISHED"
        generation["published_at"] = int(
            generation_update["ExpressionAttributeValues"][":published_at"]["N"]
        )


class FakeS3:
    def __init__(self) -> None:
        self.objects: dict[tuple[str, str], bytes] = {}

    def get_object(self, *, Bucket: str, Key: str) -> dict[str, Any]:
        return {"Body": io.BytesIO(self.objects[(Bucket, Key)])}


FAKE_TABLE = FakeTable()
FAKE_S3 = FakeS3()


class FakeResource:
    def Table(self, name: str) -> FakeTable:  # noqa: N802
        if name != "control-table":
            raise AssertionError(name)
        return FAKE_TABLE


fake_boto3 = types.ModuleType("boto3")


def fake_resource(service: str) -> FakeResource:
    if service != "dynamodb":
        raise AssertionError(service)
    return FakeResource()


def fake_client(service: str) -> FakeS3 | FakeTable:
    if service == "s3":
        return FAKE_S3
    if service == "dynamodb":
        return FAKE_TABLE
    raise AssertionError(service)


fake_boto3.resource = fake_resource  # type: ignore[attr-defined]
fake_boto3.client = fake_client  # type: ignore[attr-defined]
fake_botocore = types.ModuleType("botocore")
fake_exceptions = types.ModuleType("botocore.exceptions")
fake_exceptions.ClientError = FakeClientError  # type: ignore[attr-defined]
sys.modules.setdefault("boto3", fake_boto3)
sys.modules.setdefault("botocore", fake_botocore)
sys.modules.setdefault("botocore.exceptions", fake_exceptions)
os.environ["CONTROL_TABLE"] = "control-table"

spec = importlib.util.spec_from_file_location(
    "atlasretail_lambda_control",
    Path(__file__).parents[1] / "aws" / "lambda" / "control.py",
)
if spec is None or spec.loader is None:
    raise RuntimeError("could not load control Lambda")
control = importlib.util.module_from_spec(spec)
spec.loader.exec_module(control)


class LambdaControlTests(unittest.TestCase):
    def setUp(self) -> None:
        FAKE_TABLE.reset()
        FAKE_S3.objects.clear()
        self.event = {
            "action": "register",
            "batch_id": "b-1",
            "manifest_digest": "a" * 64,
            "manifest_uri": "s3://landing/runs/b-1/manifest.json",
            "manifest_version_id": "version-1",
        }

    def register(self, event: dict[str, Any] | None = None) -> dict[str, Any]:
        return control.handler(event or self.event, None)

    def start_and_validate(self, event: dict[str, Any] | None = None) -> tuple[str, int]:
        registered = self.register(event)
        generation_id = registered["generation_id"]
        build = control.handler(
            {"action": "start_build", "generation_id": generation_id, "execution_arn": "arn:1"},
            None,
        )
        evidence = {
            "generation_id": generation_id,
            "manifest_digest": (event or self.event)["manifest_digest"],
            "tables": {
                name: {"snapshot_id": index + 1, "rows": 10}
                for index, name in enumerate(sorted(control.EXPECTED_TABLES))
            },
        }
        FAKE_S3.objects[("evidence", f"validation/{generation_id}.json")] = json.dumps(
            evidence
        ).encode()
        validated = control.handler(
            {
                "action": "validate",
                "generation_id": generation_id,
                "validation_uri": f"s3://evidence/validation/{generation_id}.json",
                "glue_job_run_id": "jr-test",
            },
            None,
        )
        self.assertEqual("VALIDATED", validated["status"])
        return generation_id, int(build["attempt"])

    def test_registration_owns_generation_identity_and_replay(self) -> None:
        generation_id, attempt = self.start_and_validate()
        self.assertEqual(1, attempt)
        published = control.handler(
            {
                "action": "publish",
                "generation_id": generation_id,
                "expected_pointer_version": 0,
            },
            None,
        )
        self.assertEqual("PUBLISHED", published["status"])
        self.assertEqual("REPLAYED", self.register()["status"])
        resolved = control.handler({"action": "resolve"}, None)
        self.assertEqual(generation_id, resolved["generation_id"])
        self.assertEqual(1, resolved["pointer_version"])

    def test_registration_uses_the_explicit_low_level_dynamodb_client(self) -> None:
        registered = self.register()

        self.assertEqual("REGISTERED", registered["status"])
        first_put = FAKE_TABLE.last_transact_items[0]["Put"]
        self.assertEqual({"S": "BATCH#b-1"}, first_put["Item"]["pk"])
        self.assertEqual("control-table", first_put["TableName"])

    def test_failed_generation_recovers_with_same_identity(self) -> None:
        registered = self.register()
        generation_id = registered["generation_id"]
        control.handler({"action": "start_build", "generation_id": generation_id}, None)
        control.handler(
            {
                "action": "fail",
                "generation_id": generation_id,
                "failure_stage": "GLUE",
                "failure_code": "INJECTED",
            },
            None,
        )
        recovered = self.register()
        self.assertEqual("RECOVERING", recovered["status"])
        self.assertEqual(generation_id, recovered["generation_id"])
        restarted = control.handler({"action": "start_build", "generation_id": generation_id}, None)
        self.assertEqual(2, restarted["attempt"])

    def test_conflicting_batch_and_location_are_rejected(self) -> None:
        self.register()
        with self.assertRaisesRegex(ValueError, "CONFLICT"):
            self.register(dict(self.event, manifest_digest="b" * 64))
        with self.assertRaisesRegex(ValueError, "CONFLICT"):
            self.register(dict(self.event, manifest_version_id="version-2"))

    def test_registration_reconciles_a_committed_transaction_after_cancellation(self) -> None:
        FAKE_TABLE.registration_transaction_error = "TransactionCanceledException"
        FAKE_TABLE.commit_registration_before_error = True

        registered = self.register()

        self.assertEqual("IN_PROGRESS", registered["status"])
        self.assertEqual("REGISTERED", registered["generation_status"])
        self.assertEqual(1, FAKE_TABLE.transact_write_calls)
        self.assertEqual(4, FAKE_TABLE.get_item_calls)

    def test_registration_surfaces_persistent_transaction_cancellation(self) -> None:
        FAKE_TABLE.registration_transaction_error = "TransactionCanceledException"

        with self.assertRaisesRegex(FakeClientError, "TransactionCanceledException"):
            self.register()

        self.assertEqual(1, FAKE_TABLE.transact_write_calls)
        self.assertEqual(2, FAKE_TABLE.get_item_calls)
        self.assertEqual({}, FAKE_TABLE.items)

    def test_publication_requires_validation(self) -> None:
        generation_id = self.register()["generation_id"]
        with self.assertRaisesRegex(ValueError, "NOT_VALIDATED"):
            control.handler(
                {
                    "action": "publish",
                    "generation_id": generation_id,
                    "expected_pointer_version": 0,
                },
                None,
            )

    def test_stale_publication_is_rejected(self) -> None:
        first, _ = self.start_and_validate()
        control.handler(
            {"action": "publish", "generation_id": first, "expected_pointer_version": 0}, None
        )
        second_event = dict(
            self.event,
            batch_id="b-2",
            manifest_digest="b" * 64,
            manifest_uri="s3://landing/runs/b-2/manifest.json",
            manifest_version_id="version-2",
        )
        second, _ = self.start_and_validate(second_event)
        with self.assertRaisesRegex(ValueError, "STALE_PUBLISHER"):
            control.handler(
                {"action": "publish", "generation_id": second, "expected_pointer_version": 0},
                None,
            )
        self.assertEqual(first, control.handler({"action": "resolve"}, None)["generation_id"])


if __name__ == "__main__":
    unittest.main()
