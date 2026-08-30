"""Exercise the managed DynamoDB compare-and-swap path with an intentionally stale writer."""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path
from typing import Any

TABLES = (
    "orders",
    "order_lines",
    "payments",
    "returns",
    "inventory_movements",
    "products",
)


def command(*arguments: str) -> dict[str, Any]:
    result = subprocess.run(arguments, check=True, capture_output=True, text=True)
    return json.loads(result.stdout) if result.stdout.strip() else {}


def invoke(function: str, payload: dict[str, Any], output: Path) -> dict[str, Any]:
    metadata = command(
        "aws",
        "lambda",
        "invoke",
        "--function-name",
        function,
        "--cli-binary-format",
        "raw-in-base64-out",
        "--payload",
        json.dumps(payload, separators=(",", ":")),
        str(output),
        "--output",
        "json",
        "--no-cli-pager",
    )
    response = json.loads(output.read_text(encoding="utf-8"))
    return {"metadata": metadata, "response": response}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--function", required=True)
    parser.add_argument("--evidence-bucket", required=True)
    parser.add_argument("--kms-key", required=True)
    parser.add_argument("--source-registration", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--workflow-run-id", required=True)
    parser.add_argument("--output-directory", type=Path, required=True)
    arguments = parser.parse_args()
    arguments.output_directory.mkdir(parents=True, exist_ok=True)

    source = json.loads(arguments.source_registration.read_text(encoding="utf-8"))
    batch_id = f"stale-{arguments.run_id}"
    manifest_digest = "c" * 64
    registered = invoke(
        arguments.function,
        {
            "action": "register",
            "batch_id": batch_id,
            "manifest_digest": manifest_digest,
            "manifest_uri": source["manifest_uri"],
            "manifest_version_id": source["manifest_version_id"],
            "source_commit": arguments.source_commit,
            "workflow_run_id": arguments.workflow_run_id,
        },
        arguments.output_directory / "register-response.json",
    )
    generation_id = registered["response"]["generation_id"]
    invoke(
        arguments.function,
        {"action": "start_build", "generation_id": generation_id, "execution_arn": "cas-proof"},
        arguments.output_directory / "start-response.json",
    )

    validation = {
        "scope": "CONTROL_PLANE_CAS_ONLY",
        "batch_id": batch_id,
        "generation_id": generation_id,
        "manifest_digest": manifest_digest,
        "tables": {
            name: {"snapshot_id": index + 1, "rows": 1} for index, name in enumerate(TABLES)
        },
    }
    validation_path = arguments.output_directory / "validation.json"
    validation_path.write_text(
        json.dumps(validation, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    validation_key = f"validation/control-plane-stale-{arguments.run_id}.json"
    command(
        "aws",
        "s3api",
        "put-object",
        "--bucket",
        arguments.evidence_bucket,
        "--key",
        validation_key,
        "--body",
        str(validation_path),
        "--server-side-encryption",
        "aws:kms",
        "--ssekms-key-id",
        arguments.kms_key,
        "--checksum-algorithm",
        "SHA256",
        "--output",
        "json",
        "--no-cli-pager",
    )
    invoke(
        arguments.function,
        {
            "action": "validate",
            "generation_id": generation_id,
            "validation_uri": f"s3://{arguments.evidence_bucket}/{validation_key}",
        },
        arguments.output_directory / "validate-response.json",
    )
    winner_before = invoke(
        arguments.function,
        {"action": "resolve"},
        arguments.output_directory / "winner-before.json",
    )["response"]
    stale = invoke(
        arguments.function,
        {"action": "publish", "generation_id": generation_id, "expected_pointer_version": 0},
        arguments.output_directory / "publish-response.json",
    )
    error = str(stale["response"].get("errorMessage", ""))
    if stale["metadata"].get("FunctionError") != "Unhandled" or "STALE_PUBLISHER" not in error:
        raise RuntimeError("managed stale publisher was not rejected")
    winner_after = invoke(
        arguments.function,
        {"action": "resolve"},
        arguments.output_directory / "winner-after.json",
    )["response"]
    if winner_before != winner_after:
        raise RuntimeError("stale publisher changed the active winner")
    summary = {
        "result": "PASS",
        "scope": "CONTROL_PLANE_CAS_ONLY",
        "generation_id": generation_id,
        "expected_pointer_version": 0,
        "error": error,
        "source_commit": arguments.source_commit,
        "workflow_run_id": arguments.workflow_run_id,
        "winner_before": winner_before,
        "winner_after": winner_after,
    }
    (arguments.output_directory / "summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


if __name__ == "__main__":
    main()
