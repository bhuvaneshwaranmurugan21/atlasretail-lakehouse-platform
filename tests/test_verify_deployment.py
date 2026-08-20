from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from typing import Any

SCRIPT = Path(__file__).parents[1] / "scripts" / "verify_deployment.py"
SPEC = importlib.util.spec_from_file_location("verify_deployment", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)

RUN_ID = "12345"
COMMIT = "a" * 40
KMS = "arn:aws:kms:ap-south-1:887720497919:key/example"


def outputs() -> dict[str, dict[str, str]]:
    values = {
        "landing_bucket": "atlasretail-12345-landing-887720497919",
        "warehouse_bucket": "atlasretail-12345-warehouse-887720497919",
        "evidence_bucket": "atlasretail-12345-evidence-887720497919",
        "state_machine_arn": (
            "arn:aws:states:ap-south-1:887720497919:stateMachine:atlasretail-12345-pipeline"
        ),
        "glue_job_name": "atlasretail-12345-iceberg",
        "athena_workgroup": "atlasretail-12345-verification",
        "control_table": "atlasretail-12345-control",
        "glue_database": "atlasretail_12345_retail",
        "kms_key_arn": KMS,
        "kms_alias_name": "alias/atlasretail-12345",
        "glue_log_group_name": "/aws-glue/jobs/atlasretail-12345",
        "states_log_group_name": "/aws/vendedlogs/states/atlasretail-12345",
        "lambda_log_group_name": "/aws/lambda/atlasretail-12345-control",
        "glue_role_name": "atlasretail-12345-glue",
        "states_role_name": "atlasretail-12345-states",
        "lambda_role_name": "atlasretail-12345-lambda",
        "lambda_function_name": "atlasretail-12345-control",
        "pipeline_alarm_name": "atlasretail-12345-pipeline-failed",
    }
    return {name: {"value": value} for name, value in values.items()}


def successful_runner(*arguments: str) -> tuple[int, str]:
    command = " ".join(arguments)
    value: dict[str, Any]
    if arguments[0] == "terraform":
        value = {
            "values": {
                "root_module": {
                    "resources": [{"address": f"resource.{index}"} for index in range(40)]
                }
            }
        }
    elif "get-bucket-versioning" in command:
        value = {"Status": "Enabled"}
    elif "get-public-access-block" in command:
        value = {
            "PublicAccessBlockConfiguration": {
                "BlockPublicAcls": True,
                "IgnorePublicAcls": True,
                "BlockPublicPolicy": True,
                "RestrictPublicBuckets": True,
            }
        }
    elif "get-bucket-ownership-controls" in command:
        value = {"OwnershipControls": {"Rules": [{"ObjectOwnership": "BucketOwnerEnforced"}]}}
    elif "get-bucket-encryption" in command:
        value = {
            "ServerSideEncryptionConfiguration": {
                "Rules": [
                    {
                        "BucketKeyEnabled": True,
                        "ApplyServerSideEncryptionByDefault": {
                            "SSEAlgorithm": "aws:kms",
                            "KMSMasterKeyID": KMS,
                        },
                    }
                ]
            }
        }
    elif "get-bucket-lifecycle-configuration" in command:
        value = {
            "Rules": [
                {
                    "ID": "bounded-lab-expiry",
                    "Status": "Enabled",
                    "Expiration": {"Days": 7},
                    "NoncurrentVersionExpiration": {"NoncurrentDays": 7},
                    "AbortIncompleteMultipartUpload": {"DaysAfterInitiation": 1},
                }
            ]
        }
    elif "get-bucket-policy" in command:
        value = {
            "Policy": json.dumps(
                {
                    "Statement": [
                        {
                            "Effect": "Deny",
                            "Condition": {"Bool": {"aws:SecureTransport": "false"}},
                        }
                    ]
                }
            )
        }
    elif "kms describe-key" in command:
        value = {"KeyMetadata": {"KeyState": "Enabled", "Enabled": True}}
    elif "kms list-aliases" in command:
        value = {"Aliases": [{"AliasName": "alias/atlasretail-12345"}]}
    elif "dynamodb describe-table" in command:
        value = {
            "Table": {
                "TableStatus": "ACTIVE",
                "BillingModeSummary": {"BillingMode": "PAY_PER_REQUEST"},
                "SSEDescription": {"Status": "ENABLED", "KMSMasterKeyArn": KMS},
            }
        }
    elif "describe-continuous-backups" in command:
        value = {
            "ContinuousBackupsDescription": {
                "PointInTimeRecoveryDescription": {"PointInTimeRecoveryStatus": "ENABLED"}
            }
        }
    elif "dynamodb scan" in command:
        value = {"Count": 0}
    elif "glue get-database" in command:
        value = {"Database": {"Name": "atlasretail_12345_retail"}}
    elif "glue get-job-runs" in command:
        value = {"JobRuns": []}
    elif "glue get-job" in command:
        value = {
            "Job": {
                "GlueVersion": "5.0",
                "WorkerType": "G.1X",
                "NumberOfWorkers": 2,
                "Timeout": 12,
                "MaxRetries": 0,
                "ExecutionProperty": {"MaxConcurrentRuns": 1},
            }
        }
    elif "lambda get-function" in command:
        value = {
            "Configuration": {
                "State": "Active",
                "Runtime": "python3.12",
                "MemorySize": 256,
                "Timeout": 30,
                "FunctionName": "atlasretail-12345-control",
            }
        }
    elif "describe-state-machine" in command:
        value = {
            "status": "ACTIVE",
            "type": "STANDARD",
            "loggingConfiguration": {"level": "ALL"},
        }
    elif "list-executions" in command:
        value = {"executions": []}
    elif "get-work-group" in command:
        value = {
            "WorkGroup": {
                "State": "ENABLED",
                "Configuration": {
                    "EnforceWorkGroupConfiguration": True,
                    "PublishCloudWatchMetricsEnabled": True,
                    "BytesScannedCutoffPerQuery": 1073741824,
                    "ResultConfiguration": {
                        "EncryptionConfiguration": {
                            "EncryptionOption": "SSE_KMS",
                            "KmsKey": KMS,
                        }
                    },
                },
            }
        }
    elif "list-query-executions" in command:
        value = {"QueryExecutionIds": []}
    elif "describe-log-groups" in command:
        prefix = arguments[arguments.index("--log-group-name-prefix") + 1]
        value = {"logGroups": [{"logGroupName": prefix, "retentionInDays": 7}]}
    elif "filter-log-events" in command:
        value = {"events": []}
    elif "cloudwatch describe-alarms" in command:
        value = {"MetricAlarms": [{"AlarmName": "atlasretail-12345-pipeline-failed"}]}
    elif "iam get-role" in command:
        role = arguments[arguments.index("--role-name") + 1]
        service = {
            "atlasretail-12345-glue": "glue.amazonaws.com",
            "atlasretail-12345-states": "states.amazonaws.com",
            "atlasretail-12345-lambda": "lambda.amazonaws.com",
        }[role]
        value = {
            "Role": {
                "AssumeRolePolicyDocument": {"Statement": [{"Principal": {"Service": service}}]}
            }
        }
    elif "iam list-attached-role-policies" in command:
        value = {"AttachedPolicies": []}
    elif "head-object" in command:
        value = {
            "ContentLength": 100,
            "ServerSideEncryption": "aws:kms",
            "SSEKMSKeyId": KMS,
            "VersionId": "version-1",
        }
    elif "resourcegroupstaggingapi get-resources" in command:
        value = {
            "ResourceTagMappingList": [
                {
                    "ResourceARN": KMS,
                    "Tags": [
                        {"Key": "Project", "Value": "AtlasRetail"},
                        {"Key": "RunId", "Value": RUN_ID},
                        {"Key": "SourceCommit", "Value": COMMIT},
                        {"Key": "ExpiresAfter", "Value": "3-hours"},
                    ],
                }
            ]
        }
    else:
        raise AssertionError(f"Unhandled command: {command}")
    return 0, json.dumps(value)


def test_deployment_and_zero_workload_pass() -> None:
    result = MODULE.verify(outputs(), "infra/atlas", RUN_ID, COMMIT, successful_runner)

    assert result["result"] == "PASS"
    assert result["claim"] == "AWS_DEPLOYMENT_VERIFIED"
    assert result["zero_workload"] == "PASS"
    assert result["terraform_managed_resource_count"] == 40


def test_any_workload_activity_rejects_the_claim() -> None:
    def runner(*arguments: str) -> tuple[int, str]:
        if "list-query-executions" in arguments:
            return 0, json.dumps({"QueryExecutionIds": ["unexpected-query"]})
        return successful_runner(*arguments)

    result = MODULE.verify(outputs(), "infra/atlas", RUN_ID, COMMIT, runner)

    assert result["result"] == "FAIL"
    assert result["claim"] == "NONE"
    assert result["zero_workload"] == "FAIL"
