data "aws_caller_identity" "current" {}

data "aws_partition" "current" {}

resource "random_id" "suffix" {
  byte_length = 3
}

locals {
  prefix = "atlasretail-${var.run_id}"
  suffix = random_id.suffix.hex
  tags = {
    Project      = "AtlasRetail"
    ManagedBy    = "Terraform"
    RunId        = var.run_id
    SourceCommit = var.source_commit
    ExpiresAfter = "3-hours"
  }
}

resource "aws_kms_key" "lab" {
  description             = "Ephemeral AtlasRetail lab key ${var.run_id}"
  deletion_window_in_days = 7
  enable_key_rotation     = false
}

resource "aws_kms_alias" "lab" {
  name          = "alias/${local.prefix}"
  target_key_id = aws_kms_key.lab.key_id
}

module "landing_bucket" {
  source      = "./modules/bucket"
  name        = "${local.prefix}-landing-${local.suffix}"
  kms_key_arn = aws_kms_key.lab.arn
}

module "warehouse_bucket" {
  source      = "./modules/bucket"
  name        = "${local.prefix}-warehouse-${local.suffix}"
  kms_key_arn = aws_kms_key.lab.arn
}

module "evidence_bucket" {
  source      = "./modules/bucket"
  name        = "${local.prefix}-evidence-${local.suffix}"
  kms_key_arn = aws_kms_key.lab.arn
}

resource "aws_dynamodb_table" "control" {
  name         = "${local.prefix}-control"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "pk"
  range_key    = "sk"

  attribute {
    name = "pk"
    type = "S"
  }

  attribute {
    name = "sk"
    type = "S"
  }

  point_in_time_recovery {
    enabled = true
  }

  server_side_encryption {
    enabled     = true
    kms_key_arn = aws_kms_key.lab.arn
  }
}

resource "aws_glue_catalog_database" "retail" {
  name = replace("${local.prefix}_retail", "-", "_")
}

resource "aws_athena_workgroup" "verification" {
  name          = "${local.prefix}-verification"
  force_destroy = true

  configuration {
    enforce_workgroup_configuration    = true
    publish_cloudwatch_metrics_enabled = true
    bytes_scanned_cutoff_per_query     = 1073741824

    result_configuration {
      output_location = "s3://${module.evidence_bucket.name}/athena/"

      encryption_configuration {
        encryption_option = "SSE_KMS"
        kms_key_arn       = aws_kms_key.lab.arn
      }
    }
  }
}

resource "aws_s3_object" "glue_script" {
  bucket      = module.landing_bucket.name
  key         = "code/atlasretail_iceberg.py"
  source      = "${path.module}/../../aws/glue/atlasretail_iceberg.py"
  source_hash = filemd5("${path.module}/../../aws/glue/atlasretail_iceberg.py")
  kms_key_id  = aws_kms_key.lab.arn
}

resource "aws_cloudwatch_log_group" "glue" {
  name              = "/aws-glue/jobs/${local.prefix}"
  retention_in_days = 7
}

resource "aws_cloudwatch_log_group" "states" {
  name              = "/aws/vendedlogs/states/${local.prefix}"
  retention_in_days = 7
}

resource "aws_cloudwatch_log_group" "lambda" {
  name              = "/aws/lambda/${local.prefix}-control"
  retention_in_days = 7
}

resource "aws_iam_role" "glue" {
  name               = "${local.prefix}-glue"
  assume_role_policy = data.aws_iam_policy_document.glue_assume.json
}

data "aws_iam_policy_document" "glue_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["glue.amazonaws.com"]
    }
  }
}

data "aws_iam_policy_document" "glue" {
  statement {
    actions = ["s3:GetObject", "s3:PutObject", "s3:DeleteObject"]
    resources = [
      "${module.landing_bucket.arn}/*",
      "${module.warehouse_bucket.arn}/*",
      "${module.evidence_bucket.arn}/*"
    ]
  }
  statement {
    actions   = ["s3:ListBucket", "s3:GetBucketLocation"]
    resources = [module.landing_bucket.arn, module.warehouse_bucket.arn, module.evidence_bucket.arn]
  }
  statement {
    actions = [
      "glue:CreateTable",
      "glue:GetDatabase",
      "glue:GetDatabases",
      "glue:GetTable",
      "glue:GetTables",
      "glue:UpdateTable"
    ]
    resources = [
      "arn:${data.aws_partition.current.partition}:glue:${var.aws_region}:${data.aws_caller_identity.current.account_id}:catalog",
      aws_glue_catalog_database.retail.arn,
      "arn:${data.aws_partition.current.partition}:glue:${var.aws_region}:${data.aws_caller_identity.current.account_id}:table/${aws_glue_catalog_database.retail.name}/*"
    ]
  }
  statement {
    actions   = ["kms:Decrypt", "kms:Encrypt", "kms:GenerateDataKey"]
    resources = [aws_kms_key.lab.arn]
  }
  statement {
    actions   = ["logs:CreateLogStream", "logs:DescribeLogStreams", "logs:PutLogEvents"]
    resources = ["${aws_cloudwatch_log_group.glue.arn}:*"]
  }
}

resource "aws_iam_role_policy" "glue" {
  name   = "${local.prefix}-glue"
  role   = aws_iam_role.glue.id
  policy = data.aws_iam_policy_document.glue.json
}

resource "aws_glue_job" "retail" {
  name              = "${local.prefix}-iceberg"
  role_arn          = aws_iam_role.glue.arn
  glue_version      = "5.0"
  worker_type       = "G.1X"
  number_of_workers = var.glue_worker_count
  timeout           = var.glue_job_timeout_minutes
  max_retries       = 0

  command {
    name            = "glueetl"
    python_version  = "3"
    script_location = "s3://${module.landing_bucket.name}/${aws_s3_object.glue_script.key}"
  }

  default_arguments = {
    "--job-language"                     = "python"
    "--enable-continuous-cloudwatch-log" = "true"
    "--enable-metrics"                   = "true"
    "--enable-observability-metrics"     = "true"
    "--datalake-formats"                 = "iceberg"
    "--conf"                             = "spark.sql.extensions=org.apache.iceberg.spark.extensions.IcebergSparkSessionExtensions --conf spark.sql.catalog.glue_catalog=org.apache.iceberg.spark.SparkCatalog --conf spark.sql.catalog.glue_catalog.warehouse=s3://${module.warehouse_bucket.name}/iceberg/ --conf spark.sql.catalog.glue_catalog.catalog-impl=org.apache.iceberg.aws.glue.GlueCatalog --conf spark.sql.catalog.glue_catalog.io-impl=org.apache.iceberg.aws.s3.S3FileIO"
    "--TempDir"                          = "s3://${module.evidence_bucket.name}/glue-temp/"
    "--continuous-log-logGroup"          = aws_cloudwatch_log_group.glue.name
  }

  execution_property {
    max_concurrent_runs = 1
  }
}

data "archive_file" "control" {
  type        = "zip"
  source_file = "${path.module}/../../aws/lambda/control.py"
  output_path = "${path.module}/control.zip"
}

resource "aws_iam_role" "lambda" {
  name               = "${local.prefix}-lambda"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json
}

data "aws_iam_policy_document" "lambda_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

data "aws_iam_policy_document" "lambda" {
  statement {
    actions = [
      "dynamodb:GetItem",
      "dynamodb:PutItem",
      "dynamodb:TransactWriteItems",
      "dynamodb:UpdateItem"
    ]
    resources = [aws_dynamodb_table.control.arn]
  }
  statement {
    actions   = ["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["arn:${data.aws_partition.current.partition}:logs:${var.aws_region}:${data.aws_caller_identity.current.account_id}:log-group:/aws/lambda/${local.prefix}-control:*"]
  }
}

resource "aws_iam_role_policy" "lambda" {
  name   = "${local.prefix}-lambda"
  role   = aws_iam_role.lambda.id
  policy = data.aws_iam_policy_document.lambda.json
}

resource "aws_lambda_function" "control" {
  depends_on = [aws_cloudwatch_log_group.lambda]

  function_name    = "${local.prefix}-control"
  role             = aws_iam_role.lambda.arn
  handler          = "control.handler"
  runtime          = "python3.12"
  filename         = data.archive_file.control.output_path
  source_code_hash = data.archive_file.control.output_base64sha256
  memory_size      = 256
  timeout          = 30

  environment {
    variables = {
      CONTROL_TABLE = aws_dynamodb_table.control.name
    }
  }
}

resource "aws_iam_role" "states" {
  name               = "${local.prefix}-states"
  assume_role_policy = data.aws_iam_policy_document.states_assume.json
}

data "aws_iam_policy_document" "states_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["states.amazonaws.com"]
    }
  }
}

data "aws_iam_policy_document" "states" {
  statement {
    actions   = ["lambda:InvokeFunction"]
    resources = [aws_lambda_function.control.arn]
  }
  statement {
    actions   = ["glue:StartJobRun", "glue:GetJobRun", "glue:GetJobRuns", "glue:BatchStopJobRun"]
    resources = [aws_glue_job.retail.arn]
  }
  statement {
    actions = ["events:PutTargets", "events:PutRule", "events:DescribeRule"]
    resources = [
      "arn:${data.aws_partition.current.partition}:events:${var.aws_region}:${data.aws_caller_identity.current.account_id}:rule/StepFunctionsGetEventsForGlueJobsRule"
    ]
  }
  statement {
    actions = [
      "logs:CreateLogDelivery",
      "logs:GetLogDelivery",
      "logs:UpdateLogDelivery",
      "logs:DeleteLogDelivery",
      "logs:ListLogDeliveries",
      "logs:PutResourcePolicy",
      "logs:DescribeResourcePolicies",
      "logs:DescribeLogGroups"
    ]
    resources = ["*"]
  }
}

resource "aws_iam_role_policy" "states" {
  name   = "${local.prefix}-states"
  role   = aws_iam_role.states.id
  policy = data.aws_iam_policy_document.states.json
}

resource "aws_sfn_state_machine" "retail" {
  name     = "${local.prefix}-pipeline"
  role_arn = aws_iam_role.states.arn

  logging_configuration {
    include_execution_data = true
    level                  = "ALL"
    log_destination        = "${aws_cloudwatch_log_group.states.arn}:*"
  }

  definition = jsonencode({
    Comment = "AtlasRetail generation build and atomic publication"
    StartAt = "RegisterBatch"
    States = {
      RegisterBatch = {
        Type     = "Task"
        Resource = "arn:aws:states:::lambda:invoke"
        Parameters = {
          FunctionName = aws_lambda_function.control.arn
          Payload = {
            action              = "register"
            "batch_id.$"        = "$.batch_id"
            "generation_id.$"   = "$.generation_id"
            "manifest_digest.$" = "$.manifest_digest"
          }
        }
        ResultSelector = { "result.$" = "$.Payload" }
        ResultPath     = "$.registration"
        Next           = "AlreadyBuilt"
      }
      AlreadyBuilt = {
        Type = "Choice"
        Choices = [{
          Variable     = "$.registration.result.status"
          StringEquals = "REPLAYED"
          Next         = "ReplaySucceeded"
        }]
        Default = "BuildIcebergGeneration"
      }
      BuildIcebergGeneration = {
        Type     = "Task"
        Resource = "arn:aws:states:::glue:startJobRun.sync"
        Parameters = {
          JobName = aws_glue_job.retail.name
          Arguments = {
            "--SOURCE_URI.$"     = "$.source_uri"
            "--MANIFEST_URI.$"   = "$.manifest_uri"
            "--BATCH_ID.$"       = "$.batch_id"
            "--GENERATION_ID.$"  = "$.generation_id"
            "--DATABASE"         = aws_glue_catalog_database.retail.name
            "--INJECT_FAILURE.$" = "$.inject_failure"
          }
        }
        ResultPath = "$.glue"
        Next       = "PublishGeneration"
      }
      PublishGeneration = {
        Type     = "Task"
        Resource = "arn:aws:states:::lambda:invoke"
        Parameters = {
          FunctionName = aws_lambda_function.control.arn
          Payload = {
            action                       = "publish"
            "batch_id.$"                 = "$.batch_id"
            "generation_id.$"            = "$.generation_id"
            "expected_pointer_version.$" = "$.registration.result.pointer_version"
          }
        }
        ResultSelector = { "result.$" = "$.Payload" }
        ResultPath     = "$.publication"
        End            = true
      }
      ReplaySucceeded = {
        Type = "Succeed"
      }
    }
  })
}

resource "aws_cloudwatch_metric_alarm" "pipeline_failed" {
  alarm_name          = "${local.prefix}-pipeline-failed"
  alarm_description   = "A bounded AtlasRetail state-machine execution failed"
  namespace           = "AWS/States"
  metric_name         = "ExecutionsFailed"
  statistic           = "Sum"
  period              = 60
  evaluation_periods  = 1
  threshold           = 0
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"

  dimensions = {
    StateMachineArn = aws_sfn_state_machine.retail.arn
  }
}
