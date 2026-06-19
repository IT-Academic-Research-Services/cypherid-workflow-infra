variable "environment" { type = string }
variable "app_name" {
  type    = string
  default = "idseq"
}
variable "owner" { type = string }

terraform {
  required_version = ">= 1.14.3"
  required_providers {
    aws = {
      version = "~> 5.100.0"
    }
  }
  backend "s3" {
    region = "us-west-2"
  }
}

provider "aws" {
  region = "us-west-2"
  default_tags {
    tags = {
      environment = var.environment
      env         = var.environment
      owner       = var.owner
      project     = var.app_name
      application = var.app_name
      managedBy   = "terraform"
      service     = "main"
    }
  }
  ignore_tags {
    key_prefixes = ["QSConfigId-", "QSConfigName-"]
    keys         = ["Name", "environment", "env", "owner", "project", "application", "managedBy", "service"]
  }
}

module "idseq" {
  source = "./terraform"
}

output "idseq" {
  value = module.idseq
}
