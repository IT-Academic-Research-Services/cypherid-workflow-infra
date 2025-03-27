terraform {
  required_version = ">= 0.14.10"
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
