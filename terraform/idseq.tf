module "pipeline-monitor-restarter" {
  source = "./modules/pipeline-monitor-restarter"
}

module "sfn-io-helper" {
  source = "./modules/sfn-io-helper"
}

module "taxon-indexing" {
  source = "./modules/taxon-indexing"
}

module "taxon-indexing-concurrency-manager" {
  source                  = "./modules/taxon-indexing-concurrency-manager"
  deployment_environment  = var.DEPLOYMENT_ENVIRONMENT
  index_taxon_lambda_arn  = module.taxon-indexing.lambda_arn
  index_taxon_lambda_name = module.taxon-indexing.lambda_name
}

module "taxon-indexing-eviction" {
  source = "./modules/taxon-indexing-eviction"
}
