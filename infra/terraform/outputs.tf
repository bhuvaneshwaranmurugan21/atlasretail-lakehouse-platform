output "landing_bucket" {
  value = aws_s3_bucket.landing.id
}

output "lake_bucket" {
  value = aws_s3_bucket.lake.id
}

output "glue_database" {
  value = aws_glue_catalog_database.retail.name
}

output "glue_role_arn" {
  value = aws_iam_role.glue.arn
}

output "run_table" {
  value = aws_dynamodb_table.runs.name
}

output "pointer_table" {
  value = aws_dynamodb_table.pointer.name
}

output "cloudwatch_log_group" {
  value = aws_cloudwatch_log_group.pipeline.name
}

