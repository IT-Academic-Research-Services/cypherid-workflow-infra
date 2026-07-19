locals {
  # common_tags = {
  #   managedBy = "terraform"
  #   project   = "idseq"
  #   env       = var.DEPLOYMENT_ENVIRONMENT
  #   service   = "main"
  #   owner     = var.OWNER
  # }
}

module "pipeline-monitor-restarter" {
  source = "./modules/pipeline-monitor-restarter"
}

module "sfn-io-helper" {
  source = "./modules/sfn-io-helper"
}

module "taxon-indexing" {
  source                 = "./modules/taxon-indexing"
  deployment_environment = var.DEPLOYMENT_ENVIRONMENT
}

module "taxon-indexing-concurrency-manager" {
  source                  = "./modules/taxon-indexing-concurrency-manager"
  deployment_environment  = var.DEPLOYMENT_ENVIRONMENT
  index_taxon_lambda_arn  = module.taxon-indexing.lambda_arn
  index_taxon_lambda_name = module.taxon-indexing.lambda_name
  # CZID-63: bound log retention + encrypt the lambda log group with the workflows CMK.
  log_retention_in_days = var.lambda_log_retention_in_days
  log_kms_key_arn       = aws_kms_key.workflows.arn
}

module "taxon-indexing-eviction" {
  source                 = "./modules/taxon-indexing-eviction"
  deployment_environment = var.DEPLOYMENT_ENVIRONMENT
}
