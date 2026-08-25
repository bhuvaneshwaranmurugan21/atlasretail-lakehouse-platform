variable "aws_region" {
  description = "Single lab region."
  type        = string
  default     = "ap-southeast-2"

  validation {
    condition     = var.aws_region == "ap-southeast-2"
    error_message = "The bounded lab is intentionally restricted to ap-southeast-2."
  }
}

variable "run_id" {
  description = "Unique GitHub run ID used for names, tags, evidence, and teardown."
  type        = string

  validation {
    condition     = can(regex("^[0-9]{1,20}$", var.run_id))
    error_message = "run_id must be the numeric GitHub run ID."
  }
}

variable "source_commit" {
  description = "Immutable source commit represented by the evidence run."
  type        = string

  validation {
    condition     = can(regex("^[a-f0-9]{40}$", var.source_commit))
    error_message = "source_commit must be a full Git SHA."
  }
}

variable "glue_worker_count" {
  description = "Intentionally small worker count for the bounded proof."
  type        = number
  default     = 2

  validation {
    condition     = var.glue_worker_count >= 2 && var.glue_worker_count <= 3
    error_message = "The lab allows two or three G.1X workers only."
  }
}

variable "glue_job_timeout_minutes" {
  description = "Hard per-run cost and duration bound for the Glue proof job."
  type        = number
  default     = 12

  validation {
    condition = (
      var.glue_job_timeout_minutes >= 8 &&
      var.glue_job_timeout_minutes <= 15
    )
    error_message = "The bounded lab allows an 8-15 minute Glue timeout only."
  }
}
