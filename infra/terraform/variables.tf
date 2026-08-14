variable "aws_region" {
  type    = string
  default = "ap-south-1"
}

variable "environment" {
  type    = string
  default = "lab"
}

variable "run_id" {
  type = string
  validation {
    condition     = length(var.run_id) >= 8
    error_message = "run_id must contain at least eight characters."
  }
}

variable "expires_at" {
  type = string
}

