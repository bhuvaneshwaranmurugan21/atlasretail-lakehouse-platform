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
