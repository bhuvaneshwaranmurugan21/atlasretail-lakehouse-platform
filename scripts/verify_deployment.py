"""Verify the deployed AtlasRetail control plane without executing a workload."""

from __future__ import annotations

import json
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

Runner = Callable[..., tuple[int, str]]


def command(*arguments: str) -> tuple[int, str]:
    completed = subprocess.run(arguments, check=False, capture_output=True, text=True)
    return completed.returncode, completed.stdout + completed.stderr


def json_object(code: int, detail: str) -> dict[str, Any] | None:
    if code != 0:
        return None
    try:
        parsed = json.loads(detail)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def output_value(outputs: dict[str, Any], name: str) -> str:
    value = outputs.get(name, {}).get("value")
    if not isinstance(value, str) or not value:
        raise ValueError(f"Terraform output {name!r} is missing")
    return value


def terraform_resources(module: dict[str, Any]) -> list[str]:
    resources = [
        str(resource.get("address", "unknown"))
        for resource in module.get("resources", [])
        if isinstance(resource, dict)
    ]
    for child in module.get("child_modules", []):
        if isinstance(child, dict):
            resources.extend(terraform_resources(child))
    return resources


def verify(
    outputs: dict[str, Any],
    terraform_directory: str,
    run_id: str,
    source_commit: str,
    runner: Runner = command,
) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []

    def add(name: str, passed: bool, detail: Any) -> None:
        rendered = detail if isinstance(detail, str) else json.dumps(detail, sort_keys=True)
        checks.append(
            {"name": name, "result": "PASS" if passed else "FAIL", "detail": rendered[-1500:]}
        )

    def call_json(*arguments: str) -> dict[str, Any] | None:
        code, detail = runner(*arguments)
        return json_object(code, detail)

    required_outputs = (
        "landing_bucket",
        "warehouse_bucket",
        "evidence_bucket",
        "state_machine_arn",
        "glue_job_name",
        "athena_workgroup",
        "control_table",
        "glue_database",
        "kms_key_arn",
        "kms_alias_name",
        "glue_log_group_name",
        "states_log_group_name",
        "lambda_log_group_name",
        "glue_role_name",
        "states_role_name",
        "lambda_role_name",
        "lambda_function_name",
        "pipeline_alarm_name",
    )
    values: dict[str, str] = {}
    for name in required_outputs:
        try:
            values[name] = output_value(outputs, name)
        except ValueError as error:
            add(f"terraform-output:{name}", False, str(error))

    state = call_json("terraform", f"-chdir={terraform_directory}", "show", "-json")
    root = state.get("values", {}).get("root_module", {}) if state else {}
    state_resources = terraform_resources(root) if isinstance(root, dict) else []
    add(
        "terraform-state-envelope",
        len(state_resources) == 40,
        {"resource_count": len(state_resources)},
    )

    kms_arn = values.get("kms_key_arn", "")
    for output_name in ("landing_bucket", "warehouse_bucket", "evidence_bucket"):
        bucket = values.get(output_name)
        if not bucket:
            continue
        versioning = call_json(
            "aws", "s3api", "get-bucket-versioning", "--bucket", bucket, "--output", "json"
        )
        add(
            f"s3:{bucket}:versioning",
            bool(versioning and versioning.get("Status") == "Enabled"),
            versioning or {},
        )

        public = call_json(
            "aws", "s3api", "get-public-access-block", "--bucket", bucket, "--output", "json"
        )
        public_config = public.get("PublicAccessBlockConfiguration", {}) if public else {}
        add(
            f"s3:{bucket}:public-access-block",
            isinstance(public_config, dict)
            and all(
                public_config.get(key) is True
                for key in (
                    "BlockPublicAcls",
                    "IgnorePublicAcls",
                    "BlockPublicPolicy",
                    "RestrictPublicBuckets",
                )
            ),
            public_config,
        )

        ownership = call_json(
            "aws", "s3api", "get-bucket-ownership-controls", "--bucket", bucket, "--output", "json"
        )
        rules = ownership.get("OwnershipControls", {}).get("Rules", []) if ownership else []
        add(
            f"s3:{bucket}:ownership",
            any(
                isinstance(rule, dict) and rule.get("ObjectOwnership") == "BucketOwnerEnforced"
                for rule in rules
            ),
            rules,
        )

        encryption = call_json(
            "aws", "s3api", "get-bucket-encryption", "--bucket", bucket, "--output", "json"
        )
        encryption_rules = (
            encryption.get("ServerSideEncryptionConfiguration", {}).get("Rules", [])
            if encryption
            else []
        )
        encryption_ok = any(
            isinstance(rule, dict)
            and rule.get("BucketKeyEnabled") is True
            and rule.get("ApplyServerSideEncryptionByDefault", {}).get("SSEAlgorithm") == "aws:kms"
            and rule.get("ApplyServerSideEncryptionByDefault", {}).get("KMSMasterKeyID") == kms_arn
            for rule in encryption_rules
        )
        add(f"s3:{bucket}:encryption", encryption_ok, encryption_rules)

        lifecycle = call_json(
            "aws",
            "s3api",
            "get-bucket-lifecycle-configuration",
            "--bucket",
            bucket,
            "--output",
            "json",
        )
        lifecycle_rules = lifecycle.get("Rules", []) if lifecycle else []
        lifecycle_ok = any(
            isinstance(rule, dict)
            and rule.get("ID") == "bounded-lab-expiry"
            and rule.get("Status") == "Enabled"
            and rule.get("Expiration", {}).get("Days") == 7
            and rule.get("NoncurrentVersionExpiration", {}).get("NoncurrentDays") == 7
            and rule.get("AbortIncompleteMultipartUpload", {}).get("DaysAfterInitiation") == 1
            for rule in lifecycle_rules
        )
        add(f"s3:{bucket}:lifecycle", lifecycle_ok, lifecycle_rules)

        policy = call_json(
            "aws", "s3api", "get-bucket-policy", "--bucket", bucket, "--output", "json"
        )
        try:
            policy_document = json.loads(policy.get("Policy", "{}")) if policy else {}
        except json.JSONDecodeError:
            policy_document = {}
        statements = (
            policy_document.get("Statement", []) if isinstance(policy_document, dict) else []
        )
        tls_denied = any(
            isinstance(statement, dict)
            and statement.get("Effect") == "Deny"
            and statement.get("Condition", {}).get("Bool", {}).get("aws:SecureTransport") == "false"
            for statement in statements
        )
        add(f"s3:{bucket}:tls-only", tls_denied, policy_document)

        versions = call_json(
            "aws", "s3api", "list-object-versions", "--bucket", bucket, "--output", "json"
        )
        version_items = versions.get("Versions", []) if versions is not None else None
        delete_markers = versions.get("DeleteMarkers", []) if versions is not None else None
        expected_keys = ["code/atlasretail_iceberg.py"] if output_name == "landing_bucket" else []
        observed_keys = (
            sorted(item.get("Key") for item in version_items if isinstance(item, dict))
            if isinstance(version_items, list)
            else None
        )
        inventory_ok = (
            observed_keys == expected_keys
            and delete_markers == []
            and all(item.get("IsLatest") is True for item in version_items or [])
        )
        add(
            f"zero-workload:s3-inventory:{bucket}",
            inventory_ok,
            {"versions": version_items, "delete_markers": delete_markers},
        )

    if kms_arn:
        key = call_json("aws", "kms", "describe-key", "--key-id", kms_arn, "--output", "json")
        metadata = key.get("KeyMetadata", {}) if key else {}
        add(
            "kms:key-enabled",
            metadata.get("KeyState") == "Enabled" and metadata.get("Enabled") is True,
            metadata,
        )
        aliases = call_json("aws", "kms", "list-aliases", "--key-id", kms_arn, "--output", "json")
        alias_items = aliases.get("Aliases", []) if aliases else []
        add(
            "kms:alias",
            any(
                item.get("AliasName") == values.get("kms_alias_name")
                for item in alias_items
                if isinstance(item, dict)
            ),
            alias_items,
        )

    table_name = values.get("control_table")
    if table_name:
        table = call_json(
            "aws", "dynamodb", "describe-table", "--table-name", table_name, "--output", "json"
        )
        table_detail = table.get("Table", {}) if table else {}
        table_ok = (
            table_detail.get("TableStatus") == "ACTIVE"
            and table_detail.get("BillingModeSummary", {}).get("BillingMode") == "PAY_PER_REQUEST"
            and table_detail.get("SSEDescription", {}).get("Status") == "ENABLED"
            and table_detail.get("SSEDescription", {}).get("KMSMasterKeyArn") == kms_arn
        )
        add("dynamodb:configuration", table_ok, table_detail)
        backups = call_json(
            "aws",
            "dynamodb",
            "describe-continuous-backups",
            "--table-name",
            table_name,
            "--output",
            "json",
        )
        pitr = (
            backups.get("ContinuousBackupsDescription", {}).get(
                "PointInTimeRecoveryDescription", {}
            )
            if backups
            else {}
        )
        add("dynamodb:pitr", pitr.get("PointInTimeRecoveryStatus") == "ENABLED", pitr)
        scan = call_json(
            "aws",
            "dynamodb",
            "scan",
            "--table-name",
            table_name,
            "--select",
            "COUNT",
            "--output",
            "json",
        )
        add("zero-workload:dynamodb", bool(scan and scan.get("Count") == 0), scan or {})

    database_name = values.get("glue_database")
    if database_name:
        database = call_json(
            "aws", "glue", "get-database", "--name", database_name, "--output", "json"
        )
        add(
            "glue:database",
            bool(database and database.get("Database", {}).get("Name") == database_name),
            database or {},
        )
        tables = call_json(
            "aws", "glue", "get-tables", "--database-name", database_name, "--output", "json"
        )
        add(
            "zero-workload:glue-tables",
            bool(tables is not None and tables.get("TableList") == []),
            tables or {},
        )

    job_name = values.get("glue_job_name")
    if job_name:
        job = call_json("aws", "glue", "get-job", "--job-name", job_name, "--output", "json")
        job_detail = job.get("Job", {}) if job else {}
        execution = job_detail.get("ExecutionProperty", {})
        job_ok = (
            job_detail.get("GlueVersion") == "5.0"
            and job_detail.get("WorkerType") == "G.1X"
            and job_detail.get("NumberOfWorkers") == 2
            and job_detail.get("Timeout") == 12
            and job_detail.get("MaxRetries") == 0
            and execution.get("MaxConcurrentRuns") == 1
        )
        add("glue:job-configuration", job_ok, job_detail)
        runs = call_json(
            "aws",
            "glue",
            "get-job-runs",
            "--job-name",
            job_name,
            "--max-results",
            "1",
            "--output",
            "json",
        )
        add("zero-workload:glue", bool(runs is not None and runs.get("JobRuns") == []), runs or {})

    function_name = values.get("lambda_function_name")
    if function_name:
        function = call_json(
            "aws", "lambda", "get-function", "--function-name", function_name, "--output", "json"
        )
        configuration = function.get("Configuration", {}) if function else {}
        lambda_ok = (
            configuration.get("State") == "Active"
            and configuration.get("Runtime") == "python3.12"
            and configuration.get("MemorySize") == 256
            and configuration.get("Timeout") == 30
            and configuration.get("FunctionName") == function_name
        )
        add("lambda:configuration", lambda_ok, configuration)

    state_machine_arn = values.get("state_machine_arn")
    if state_machine_arn:
        machine = call_json(
            "aws",
            "stepfunctions",
            "describe-state-machine",
            "--state-machine-arn",
            state_machine_arn,
            "--output",
            "json",
        )
        logging = machine.get("loggingConfiguration", {}) if machine else {}
        machine_ok = bool(
            machine
            and machine.get("status") == "ACTIVE"
            and machine.get("type") == "STANDARD"
            and logging.get("level") == "ALL"
        )
        add("stepfunctions:configuration", machine_ok, machine or {})
        executions = call_json(
            "aws",
            "stepfunctions",
            "list-executions",
            "--state-machine-arn",
            state_machine_arn,
            "--max-results",
            "1",
            "--output",
            "json",
        )
        add(
            "zero-workload:stepfunctions",
            bool(executions is not None and executions.get("executions") == []),
            executions or {},
        )

    workgroup_name = values.get("athena_workgroup")
    if workgroup_name:
        workgroup = call_json(
            "aws", "athena", "get-work-group", "--work-group", workgroup_name, "--output", "json"
        )
        workgroup_detail = workgroup.get("WorkGroup", {}) if workgroup else {}
        configuration = workgroup_detail.get("Configuration", {})
        result_configuration = configuration.get("ResultConfiguration", {})
        athena_ok = (
            workgroup_detail.get("State") == "ENABLED"
            and configuration.get("EnforceWorkGroupConfiguration") is True
            and configuration.get("PublishCloudWatchMetricsEnabled") is True
            and configuration.get("BytesScannedCutoffPerQuery") == 1073741824
            and result_configuration.get("EncryptionConfiguration", {}).get("EncryptionOption")
            == "SSE_KMS"
            and result_configuration.get("EncryptionConfiguration", {}).get("KmsKey") == kms_arn
        )
        add("athena:workgroup-configuration", athena_ok, workgroup_detail)
        queries = call_json(
            "aws",
            "athena",
            "list-query-executions",
            "--work-group",
            workgroup_name,
            "--max-results",
            "1",
            "--output",
            "json",
        )
        add(
            "zero-workload:athena",
            bool(queries is not None and queries.get("QueryExecutionIds") == []),
            queries or {},
        )

    for output_name in ("glue_log_group_name", "states_log_group_name", "lambda_log_group_name"):
        log_group = values.get(output_name)
        if not log_group:
            continue
        groups = call_json(
            "aws",
            "logs",
            "describe-log-groups",
            "--log-group-name-prefix",
            log_group,
            "--output",
            "json",
        )
        exact = [
            item
            for item in (groups or {}).get("logGroups", [])
            if item.get("logGroupName") == log_group
        ]
        add(
            f"cloudwatch-logs:{log_group}",
            len(exact) == 1 and exact[0].get("retentionInDays") == 7,
            exact,
        )
        events = call_json(
            "aws",
            "logs",
            "filter-log-events",
            "--log-group-name",
            log_group,
            "--limit",
            "1",
            "--output",
            "json",
        )
        add(
            f"zero-workload:cloudwatch-logs:{log_group}",
            bool(events is not None and events.get("events") == []),
            events or {},
        )

    alarm_name = values.get("pipeline_alarm_name")
    if alarm_name:
        alarms = call_json(
            "aws", "cloudwatch", "describe-alarms", "--alarm-names", alarm_name, "--output", "json"
        )
        exact_alarms = [
            alarm
            for alarm in (alarms or {}).get("MetricAlarms", [])
            if alarm.get("AlarmName") == alarm_name
        ]
        add("cloudwatch:alarm", len(exact_alarms) == 1, exact_alarms)

    expected_services = {
        "glue_role_name": "glue.amazonaws.com",
        "states_role_name": "states.amazonaws.com",
        "lambda_role_name": "lambda.amazonaws.com",
    }
    for output_name, expected_service in expected_services.items():
        role_name = values.get(output_name)
        if not role_name:
            continue
        role = call_json("aws", "iam", "get-role", "--role-name", role_name, "--output", "json")
        document = role.get("Role", {}).get("AssumeRolePolicyDocument", {}) if role else {}
        statements = document.get("Statement", []) if isinstance(document, dict) else []
        service_values = {
            statement.get("Principal", {}).get("Service")
            for statement in statements
            if isinstance(statement, dict)
        }
        add(
            f"iam:{role_name}:trust",
            service_values == {expected_service},
            sorted(str(item) for item in service_values),
        )
        attached = call_json(
            "aws",
            "iam",
            "list-attached-role-policies",
            "--role-name",
            role_name,
            "--output",
            "json",
        )
        add(
            f"iam:{role_name}:no-managed-policies",
            bool(attached is not None and attached.get("AttachedPolicies") == []),
            attached or {},
        )

    landing = values.get("landing_bucket")
    if landing:
        script_object = call_json(
            "aws",
            "s3api",
            "head-object",
            "--bucket",
            landing,
            "--key",
            "code/atlasretail_iceberg.py",
            "--output",
            "json",
        )
        object_ok = bool(
            script_object
            and script_object.get("ContentLength", 0) > 0
            and script_object.get("ServerSideEncryption") == "aws:kms"
            and script_object.get("SSEKMSKeyId") == kms_arn
            and script_object.get("VersionId")
        )
        add("s3:glue-script-object", object_ok, script_object or {})

    inventory = call_json(
        "aws",
        "resourcegroupstaggingapi",
        "get-resources",
        "--tag-filters",
        f"Key=RunId,Values={run_id}",
        "--output",
        "json",
    )
    mappings = inventory.get("ResourceTagMappingList", []) if inventory else []
    tags_ok = bool(mappings) and all(
        {tag.get("Key"): tag.get("Value") for tag in mapping.get("Tags", [])}.get("Project")
        == "AtlasRetail"
        and {tag.get("Key"): tag.get("Value") for tag in mapping.get("Tags", [])}.get(
            "SourceCommit"
        )
        == source_commit
        and {tag.get("Key"): tag.get("Value") for tag in mapping.get("Tags", [])}.get(
            "ExpiresAfter"
        )
        == "3-hours"
        for mapping in mappings
        if isinstance(mapping, dict)
    )
    add("tags:run-envelope", tags_ok, {"tagged_resource_count": len(mappings)})

    zero_checks = [item for item in checks if item["name"].startswith("zero-workload:")]
    all_pass = all(item["result"] == "PASS" for item in checks)
    return {
        "result": "PASS" if all_pass else "FAIL",
        "claim": "AWS_DEPLOYMENT_VERIFIED" if all_pass else "NONE",
        "terraform_managed_resource_count": len(state_resources),
        "zero_workload": "PASS"
        if zero_checks and all(item["result"] == "PASS" for item in zero_checks)
        else "FAIL",
        "checks": checks,
    }


def main(arguments: list[str]) -> int:
    if len(arguments) != 6:
        print(
            "usage: verify_deployment.py OUTPUTS_JSON TF_DIR RUN_ID SOURCE_COMMIT OUTPUT_JSON",
            file=sys.stderr,
        )
        return 2
    try:
        parsed = json.loads(Path(arguments[1]).read_text(encoding="utf-8"))
        outputs = parsed if isinstance(parsed, dict) else {}
    except (OSError, json.JSONDecodeError):
        outputs = {}
    result = verify(outputs, arguments[2], arguments[3], arguments[4])
    output = Path(arguments[5])
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return 0 if result["result"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
