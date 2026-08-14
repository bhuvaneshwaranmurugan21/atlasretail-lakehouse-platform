output "landing_bucket" {
  value = module.landing_bucket.name
}

output "warehouse_bucket" {
  value = module.warehouse_bucket.name
}

output "evidence_bucket" {
  value = module.evidence_bucket.name
}

output "state_machine_arn" {
  value = aws_sfn_state_machine.retail.arn
}

output "glue_job_name" {
  value = aws_glue_job.retail.name
}

output "athena_workgroup" {
  value = aws_athena_workgroup.verification.name
}

output "control_table" {
  value = aws_dynamodb_table.control.name
}

output "glue_database" {
  value = aws_glue_catalog_database.retail.name
}

output "kms_key_arn" {
  value = aws_kms_key.lab.arn
}

output "kms_alias_name" {
  value = aws_kms_alias.lab.name
}

output "glue_log_group_name" {
  value = aws_cloudwatch_log_group.glue.name
}

output "states_log_group_name" {
  value = aws_cloudwatch_log_group.states.name
}

output "lambda_log_group_name" {
  value = aws_cloudwatch_log_group.lambda.name
}

output "glue_role_name" {
  value = aws_iam_role.glue.name
}

output "states_role_name" {
  value = aws_iam_role.states.name
}

output "lambda_role_name" {
  value = aws_iam_role.lambda.name
}

output "lambda_function_name" {
  value = aws_lambda_function.control.function_name
}

output "pipeline_alarm_name" {
  value = aws_cloudwatch_metric_alarm.pipeline_failed.alarm_name
}
