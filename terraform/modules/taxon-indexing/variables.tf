variable "deployment_environment" {
  type        = string
  description = "deployment environment: (test, dev, staging, prod, sandbox)"
}

variable "log_retention_in_days" {
  type        = number
  default     = 90
  description = "CloudWatch Logs retention in days for the taxon-indexing worker lambda log group (CZID-63)."
}

variable "log_kms_key_arn" {
  type        = string
  default     = null
  description = "KMS key ARN to encrypt the taxon-indexing worker lambda log group (CZID-63). Null uses the AWS-managed key."
}
