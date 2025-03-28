terraform {
  required_version = ">= 1.11.3"
  required_providers {
    aws = {
      version = "~> 4.54"
    }
  }
  backend "s3" {
    region = "us-west-2"
  }
}

module "idseq" {
  source = "./terraform"
}

output "idseq" {
  value = module.idseq
}
