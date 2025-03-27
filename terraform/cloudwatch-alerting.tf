module "cloudwatch-alerting" {
  source                 = "./modules/cloudwatch-alerting"
  deployment_environment = var.DEPLOYMENT_ENVIRONMENT
  # Module count/for_each are scheduled for release in Terraform 0.13.
  # Until they are available, disable the subscription filters but deploy the rest of the module in inactive envs.
  log_group_subscription_filters = var.DEPLOYMENT_ENVIRONMENT == "prod" ? {
    "ecs-logs-prod" : "",
    "/aws/batch/job" : "",
    "/aws/lambda/taxon-indexing-eviction-lambda-prod-evict_taxons" : ""
    } : var.DEPLOYMENT_ENVIRONMENT == "staging" ? {
    "ecs-logs-staging" : "",
    "/aws/batch/job" : "",
    "/aws/lambda/taxon-indexing-eviction-lambda-staging-evict_taxons" : ""
  } : {}
  alerts_slack_channel          = var.ALERTS_SLACK_CHANNEL
  alerts_slack_channel_id       = var.ALERTS_SLACK_CHANNEL_ID
  slack_oauth_token_secret_name = var.SLACK_OAUTH_TOKEN_SECRET_NAME
}
