variable "environment" { type = string }
variable "app_name" { 
    type = string
    default = "idseq"
}
variable "owner" { type = string }

terraform {
  required_version = ">= 1.14.3"
  required_providers {
    aws = {
      version = "~> 4.54"
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
        owner = var.owner
        application = var.app_name
        managedBy = "terraform"
      }
    }
}

module "idseq" {
  source = "./terraform"
}

output "idseq" {
  value = module.idseq
}
