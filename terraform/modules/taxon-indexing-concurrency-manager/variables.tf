variable "deployment_environment" {
  type        = string
  description = "deployment environment: (test, dev, staging, prod)"
}

variable "index_taxon_lambda_arn" {
  type        = string
  description = "ARN of the index taxon lambda"
}

variable "index_taxon_lambda_name" {
  type        = string
  description = "Name of the index taxon lambda"
}

variable "log_retention_in_days" {
  type        = number
  default     = 90
  description = "CloudWatch Logs retention in days for the concurrency-manager lambda log group (CZID-63)."
}

variable "log_kms_key_arn" {
  type        = string
  default     = null
  description = "KMS key ARN to encrypt the concurrency-manager lambda log group (CZID-63). Null uses the AWS-managed key."
}
