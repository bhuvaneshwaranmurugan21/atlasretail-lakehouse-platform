"""Canonical Terraform address envelopes for the bounded AtlasRetail deployment."""

EXPECTED_MANAGED_ADDRESSES = frozenset(
    {
        "aws_athena_workgroup.verification",
        "aws_cloudwatch_log_group.glue",
        "aws_cloudwatch_log_group.lambda",
        "aws_cloudwatch_log_group.states",
        "aws_cloudwatch_metric_alarm.pipeline_failed",
        "aws_dynamodb_table.control",
        "aws_glue_catalog_database.retail",
        "aws_glue_job.retail",
        "aws_iam_role.glue",
        "aws_iam_role.lambda",
        "aws_iam_role.states",
        "aws_iam_role_policy.glue",
        "aws_iam_role_policy.lambda",
        "aws_iam_role_policy.states",
        "aws_kms_alias.lab",
        "aws_kms_key.lab",
        "aws_lambda_function.control",
        "aws_s3_object.glue_script",
        "aws_sfn_state_machine.retail",
        *{
            f"module.{module}.{resource}.this"
            for module in ("landing_bucket", "warehouse_bucket", "evidence_bucket")
            for resource in (
                "aws_s3_bucket",
                "aws_s3_bucket_lifecycle_configuration",
                "aws_s3_bucket_ownership_controls",
                "aws_s3_bucket_policy",
                "aws_s3_bucket_public_access_block",
                "aws_s3_bucket_server_side_encryption_configuration",
                "aws_s3_bucket_versioning",
            )
        },
    }
)

EXPECTED_DATA_ADDRESSES = frozenset(
    {
        "data.aws_iam_policy_document.glue",
        "data.aws_iam_policy_document.lambda",
        "data.aws_iam_policy_document.states",
        "module.evidence_bucket.data.aws_iam_policy_document.tls",
        "module.landing_bucket.data.aws_iam_policy_document.tls",
        "module.warehouse_bucket.data.aws_iam_policy_document.tls",
    }
)
