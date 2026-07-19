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

# log_retention_in_days / log_kms_key_arn were removed alongside the managed log group resource
# (see the CZID-63 follow-up note in main.tf). Re-add them when the log group is re-adopted.
