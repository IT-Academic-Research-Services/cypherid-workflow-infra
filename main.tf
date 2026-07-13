variable "environment" { type = string }
variable "app_name" {
  type    = string
  default = "idseq"
}
variable "owner" { type = string }

terraform {
  # required_version + required_providers live in versions.tf (CZID-169 SSOT).
  backend "s3" {
    region = "us-west-2"
    # S3-native state locking (Terraform/TF >= 1.10): writes a <key>.tflock object
    # alongside the state so concurrent applies can't corrupt it. No DynamoDB
    # table required. (CZID-29 / STATE-1.)
    use_lockfile = true
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
    keys         = ["environment", "env", "owner", "project", "application", "managedBy"]
  }
}

module "idseq" {
  source = "./terraform"
}

output "idseq" {
  value = module.idseq
}
