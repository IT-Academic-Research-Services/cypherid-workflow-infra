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
