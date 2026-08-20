data "aws_caller_identity" "current" {}

data "aws_partition" "current" {}

locals {
  prefix                = "atlasretail-${var.run_id}"
  landing_bucket_name   = "${local.prefix}-landing-${data.aws_caller_identity.current.account_id}"
  warehouse_bucket_name = "${local.prefix}-warehouse-${data.aws_caller_identity.current.account_id}"
  evidence_bucket_name  = "${local.prefix}-evidence-${data.aws_caller_identity.current.account_id}"
  glue_database_name    = replace("${local.prefix}_retail", "-", "_")
  glue_job_name         = "${local.prefix}-iceberg"
  lambda_function_name  = "${local.prefix}-control"
  lambda_function_arn   = "arn:${data.aws_partition.current.partition}:lambda:${var.aws_region}:${data.aws_caller_identity.current.account_id}:function:${local.lambda_function_name}"
  tags = {
    Project      = "AtlasRetail"
    ManagedBy    = "Terraform"
    RunId        = var.run_id
    SourceCommit = var.source_commit
    ExpiresAfter = "3-hours"
  }
  lambda_retry = [{
    ErrorEquals = [
      "Lambda.ServiceException",
      "Lambda.AWSLambdaException",
      "Lambda.SdkClientException",
      "Lambda.TooManyRequestsException"
    ]
    IntervalSeconds = 2
    MaxAttempts     = 3
    BackoffRate     = 2
  }]
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
  name        = local.landing_bucket_name
  kms_key_arn = aws_kms_key.lab.arn
}

module "warehouse_bucket" {
  source      = "./modules/bucket"
  name        = local.warehouse_bucket_name
  kms_key_arn = aws_kms_key.lab.arn
}

module "evidence_bucket" {
  source      = "./modules/bucket"
  name        = local.evidence_bucket_name
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
  name = local.glue_database_name
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
    actions = [
      "s3:GetObject",
      "s3:GetObjectAttributes",
      "s3:GetObjectVersion",
      "s3:PutObject",
      "s3:DeleteObject"
    ]
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
  name              = local.glue_job_name
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
      "dynamodb:TransactWriteItems",
      "dynamodb:UpdateItem"
    ]
    resources = [aws_dynamodb_table.control.arn]
  }
  statement {
    actions   = ["s3:GetObject"]
    resources = ["${module.evidence_bucket.arn}/validation/*"]
  }
  statement {
    actions   = ["kms:Decrypt"]
    resources = [aws_kms_key.lab.arn]
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

  function_name    = local.lambda_function_name
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
  # The role ARN alone does not make Terraform wait for its inline policy.
  # Enforce policy attachment before Step Functions validates log delivery.
  depends_on = [aws_iam_role_policy.states]

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
          FunctionName = local.lambda_function_arn
          Payload = {
            action                  = "register"
            "batch_id.$"            = "$.batch_id"
            "manifest_digest.$"     = "$.manifest_digest"
            "manifest_uri.$"        = "$.manifest_uri"
            "manifest_version_id.$" = "$.manifest_version_id"
            "source_commit.$"       = "$.source_commit"
            "workflow_run_id.$"     = "$.workflow_run_id"
          }
        }
        ResultSelector = { "result.$" = "$.Payload" }
        Retry          = local.lambda_retry
        ResultPath     = "$.registration"
        Next           = "AlreadyBuilt"
      }
      AlreadyBuilt = {
        Type = "Choice"
        Choices = [{
          Variable     = "$.registration.result.status"
          StringEquals = "REPLAYED"
          Next         = "ReplaySucceeded"
          }, {
          Variable     = "$.registration.result.status"
          StringEquals = "IN_PROGRESS"
          Next         = "ConcurrentExecutionRejected"
        }]
        Default = "StartGenerationBuild"
      }
      StartGenerationBuild = {
        Type     = "Task"
        Resource = "arn:aws:states:::lambda:invoke"
        Parameters = {
          FunctionName = local.lambda_function_arn
          Payload = {
            action            = "start_build"
            "generation_id.$" = "$.registration.result.generation_id"
            "execution_arn.$" = "$$.Execution.Id"
          }
        }
        ResultSelector = { "result.$" = "$.Payload" }
        Retry          = local.lambda_retry
        ResultPath     = "$.build"
        Next           = "BuildIcebergGeneration"
      }
      BuildIcebergGeneration = {
        Type     = "Task"
        Resource = "arn:aws:states:::glue:startJobRun.sync"
        Parameters = {
          JobName = local.glue_job_name
          Arguments = {
            "--MANIFEST_URI.$"        = "$.manifest_uri"
            "--MANIFEST_VERSION_ID.$" = "$.manifest_version_id"
            "--MANIFEST_DIGEST.$"     = "$.manifest_digest"
            "--BATCH_ID.$"            = "$.batch_id"
            "--GENERATION_ID.$"       = "$.registration.result.generation_id"
            "--DATABASE"              = local.glue_database_name
            "--VALIDATION_URI.$"      = "States.Format('s3://${local.evidence_bucket_name}/validation/{}.json', $.registration.result.generation_id)"
            "--INJECT_FAILURE.$"      = "$.inject_failure"
          }
        }
        ResultPath = "$.glue"
        Next       = "ValidateGeneration"
        Catch = [{
          ErrorEquals = ["States.ALL"]
          ResultPath  = "$.failure"
          Next        = "MarkGlueFailure"
        }]
      }
      ValidateGeneration = {
        Type     = "Task"
        Resource = "arn:aws:states:::lambda:invoke"
        Parameters = {
          FunctionName = local.lambda_function_arn
          Payload = {
            action              = "validate"
            "generation_id.$"   = "$.registration.result.generation_id"
            "validation_uri.$"  = "States.Format('s3://${local.evidence_bucket_name}/validation/{}.json', $.registration.result.generation_id)"
            "glue_job_run_id.$" = "$.glue.JobRunId"
          }
        }
        ResultSelector = { "result.$" = "$.Payload" }
        Retry          = local.lambda_retry
        ResultPath     = "$.validation"
        Next           = "PublishGeneration"
        Catch = [{
          ErrorEquals = ["States.ALL"]
          ResultPath  = "$.failure"
          Next        = "MarkValidationFailure"
        }]
      }
      PublishGeneration = {
        Type     = "Task"
        Resource = "arn:aws:states:::lambda:invoke"
        Parameters = {
          FunctionName = local.lambda_function_arn
          Payload = {
            action                       = "publish"
            "generation_id.$"            = "$.registration.result.generation_id"
            "expected_pointer_version.$" = "$.registration.result.pointer_version"
          }
        }
        ResultSelector = { "result.$" = "$.Payload" }
        Retry          = local.lambda_retry
        ResultPath     = "$.publication"
        End            = true
        Catch = [{
          ErrorEquals = ["States.ALL"]
          ResultPath  = "$.failure"
          Next        = "MarkPublicationFailure"
        }]
      }
      ReplaySucceeded = {
        Type = "Succeed"
      }
      ConcurrentExecutionRejected = {
        Type  = "Fail"
        Error = "BATCH_IN_PROGRESS"
        Cause = "The accepted batch already has a non-terminal generation"
      }
      MarkGlueFailure = {
        Type     = "Task"
        Resource = "arn:aws:states:::lambda:invoke"
        Parameters = {
          FunctionName = local.lambda_function_arn
          Payload = {
            action            = "fail"
            "generation_id.$" = "$.registration.result.generation_id"
            failure_stage     = "GLUE"
            "failure_code.$"  = "States.JsonToString($.failure)"
          }
        }
        Retry = local.lambda_retry
        Next  = "GenerationFailed"
      }
      MarkValidationFailure = {
        Type     = "Task"
        Resource = "arn:aws:states:::lambda:invoke"
        Parameters = {
          FunctionName = local.lambda_function_arn
          Payload = {
            action            = "fail"
            "generation_id.$" = "$.registration.result.generation_id"
            failure_stage     = "VALIDATION"
            "failure_code.$"  = "States.JsonToString($.failure)"
          }
        }
        Retry = local.lambda_retry
        Next  = "GenerationFailed"
      }
      MarkPublicationFailure = {
        Type     = "Task"
        Resource = "arn:aws:states:::lambda:invoke"
        Parameters = {
          FunctionName = local.lambda_function_arn
          Payload = {
            action            = "fail"
            "generation_id.$" = "$.registration.result.generation_id"
            failure_stage     = "PUBLICATION"
            "failure_code.$"  = "States.JsonToString($.failure)"
          }
        }
        Retry = local.lambda_retry
        Next  = "GenerationFailed"
      }
      GenerationFailed = {
        Type  = "Fail"
        Error = "GENERATION_FAILED"
        Cause = "Generation failed before atomic publication"
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
