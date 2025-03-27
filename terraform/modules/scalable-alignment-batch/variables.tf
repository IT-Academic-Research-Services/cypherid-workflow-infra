// Environment Variables

variable "region" {
  type        = string
  description = "aws region"
}

variable "deployment_environment" {
  type        = string
  description = "deployment environment: (test, dev, staging, prod)"
}

variable "docker_registry" {
  type        = string
  description = "ecr docker registry"
}

variable "owner" {
  type        = string
  description = "resource owner contact email"
}

variable "max_vcpus" {
  type        = map(any)
  description = "size limit for batch compute environments, by deployment env and provisioning model"
}

variable "min_vcpus" {
  type        = map(any)
  description = "minimum size limit for batch compute environments, by deployment env and provisioning model"
}

// Network Variables

variable "security_group_id" {
  type        = string
  description = "security group for batch compute environment"
}

variable "subnet_ids" {
  type        = list(string)
  description = "subnet IDs for batch compute environment"
}

// Role Variables

variable "job_iam_role" {
  type        = string
  description = "iam role arn for the batch job definition"
}

variable "service_iam_role" {
  type        = string
  description = "iam role arn for the batch compute environment"
}

variable "spot_fleet_iam_role" {
  type        = string
  description = "iam role arn for the spot fleet within the batch compute environment"
}

// Priority Variables

variable "priorities" {
  type        = list(map(string))
  description = ""
}

// Alignment Variables

variable "alignment_algorithm" {
  type        = string
  description = "which alignment algorithm to use (gsnap, rapsearch2)"
}

// Utility Variables

variable "disabled" {
  type        = bool
  description = "if this is set to true no resources will be created"
}

