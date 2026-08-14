from __future__ import annotations

import importlib.util
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


class FakeTable:
    def __init__(self) -> None:
        self.items: dict[tuple[str, str], dict[str, Any]] = {}
        self.meta = types.SimpleNamespace(client=self)

    def reset(self) -> None:
        self.items.clear()

    def get_item(self, *, Key: dict[str, str], ConsistentRead: bool) -> dict[str, Any]:
        del ConsistentRead
        item = self.items.get((Key["pk"], Key["sk"]))
        return {"Item": dict(item)} if item else {}

    def put_item(self, *, Item: dict[str, Any], ConditionExpression: str) -> None:
        del ConditionExpression
        key = (Item["pk"], Item["sk"])
        if key in self.items:
            raise FakeClientError("ConditionalCheckFailedException")
        self.items[key] = dict(Item)

    def transact_write_items(self, *, TransactItems: list[dict[str, Any]]) -> None:
        pointer_update, batch_update = (item["Update"] for item in TransactItems)
        pointer_values = pointer_update["ExpressionAttributeValues"]
        expected = int(pointer_values[":expected"]["N"])
        current_pointer = self.items.get(("CONTROL", "ACTIVE"))
        actual = int(current_pointer["pointer_version"]) if current_pointer else 0
        batch_key = (
            batch_update["Key"]["pk"]["S"],
            batch_update["Key"]["sk"]["S"],
        )
        batch = self.items[batch_key]
        generation = batch_update["ExpressionAttributeValues"][":generation"]["S"]
        if actual != expected or batch["generation_id"] != generation:
            raise FakeClientError("TransactionCanceledException")

        self.items[("CONTROL", "ACTIVE")] = {
            "pk": "CONTROL",
            "sk": "ACTIVE",
            "active_generation": pointer_values[":generation"]["S"],
            "pointer_version": int(pointer_values[":next"]["N"]),
            "published_at": int(pointer_values[":published_at"]["N"]),
        }
        batch_values = batch_update["ExpressionAttributeValues"]
        batch["status"] = batch_values[":published"]["S"]
        batch["published_at"] = int(batch_values[":published_at"]["N"])


FAKE_TABLE = FakeTable()


class FakeResource:
    def Table(self, name: str) -> FakeTable:  # noqa: N802 - boto3 interface
        if name != "control-table":
            raise AssertionError(name)
        return FAKE_TABLE


fake_boto3 = types.ModuleType("boto3")


def fake_resource(service: str) -> FakeResource:
    if service != "dynamodb":
        raise AssertionError(service)
    return FakeResource()


fake_boto3.resource = fake_resource  # type: ignore[attr-defined]
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
        self.event = {
            "action": "register",
            "batch_id": "b-1",
            "generation_id": "g-b-1",
            "manifest_digest": "a" * 64,
        }

    def test_register_publish_and_replay(self) -> None:
        registered = control.handler(self.event, None)
        self.assertEqual("REGISTERED", registered["status"])
        published = control.handler(
            {
                "action": "publish",
                "batch_id": "b-1",
                "generation_id": "g-b-1",
                "expected_pointer_version": 0,
            },
            None,
        )
        self.assertEqual(
            {"status": "PUBLISHED", "generation_id": "g-b-1", "pointer_version": 1}, published
        )
        self.assertEqual("REPLAYED", control.handler(self.event, None)["status"])

    def test_failed_registration_recovers(self) -> None:
        control.handler(self.event, None)
        self.assertEqual("RECOVERING", control.handler(self.event, None)["status"])

    def test_conflicting_batch_is_rejected(self) -> None:
        control.handler(self.event, None)
        conflict = dict(self.event, manifest_digest="b" * 64)
        with self.assertRaisesRegex(ValueError, "CONFLICT"):
            control.handler(conflict, None)

    def test_stale_publication_is_rejected(self) -> None:
        control.handler(self.event, None)
        with self.assertRaisesRegex(ValueError, "STALE_PUBLISHER"):
            control.handler(
                {
                    "action": "publish",
                    "batch_id": "b-1",
                    "generation_id": "g-b-1",
                    "expected_pointer_version": 1,
                },
                None,
            )
        self.assertEqual("REGISTERED", FAKE_TABLE.items[("BATCH#b-1", "IDENTITY")]["status"])
        self.assertNotIn(("CONTROL", "ACTIVE"), FAKE_TABLE.items)


if __name__ == "__main__":
    unittest.main()
