import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TERRAFORM = (ROOT / "infra" / "atlas" / "main.tf").read_text(encoding="utf-8")
CONTROL = (ROOT / "aws" / "lambda" / "control.py").read_text(encoding="utf-8")


def test_lambda_runtime_policy_authorizes_transaction_item_operations() -> None:
    policy = TERRAFORM.split('data "aws_iam_policy_document" "lambda" {', 1)[1].split(
        'resource "aws_iam_role_policy" "lambda"', 1
    )[0]
    actions_block = policy.split("actions = [", 1)[1].split("]", 1)[0]
    actions = set(re.findall(r'"([^"]+)"', actions_block))

    transaction_permissions = {
        "Put": "dynamodb:PutItem",
        "Update": "dynamodb:UpdateItem",
    }
    for operation, permission in transaction_permissions.items():
        if f'"{operation}": {{' in CONTROL:
            assert permission in actions

    assert "dynamodb:TransactWriteItems" in actions
    assert "resources = [aws_dynamodb_table.control.arn]" in policy
