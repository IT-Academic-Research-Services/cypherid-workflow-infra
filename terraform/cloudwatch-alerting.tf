# =============================================================================
# CZID-447 — log-based CloudWatch -> Slack alerting.
# -----------------------------------------------------------------------------
# This module subscribes a scan-and-alert Lambda to a set of log groups (ECS
# app logs, /aws/batch/job, the taxon-indexing-eviction lambda) and posts to a
# Slack channel on matching log events.
#
# It was previously hard-disabled with `count = 0` and a comment claiming module
# count/for_each were "scheduled for release in Terraform 0.13". Those shipped in
# TF 0.13 (Aug 2020); this repo now targets TF >= 1.x, so the workaround was stale
# and left log-based alerting OFF in EVERY environment, including prod.
#
# Re-enabled here behind a real per-env toggle (var.enable_cloudwatch_alerting):
#   - Defaults to "auto": ON only where there is something to alert on AND a Slack
#     token is wired up — i.e. the subscription-filter map is non-empty (prod +
#     staging, below) AND var.SLACK_OAUTH_TOKEN_SECRET_NAME is set. dev/sandbox/
#     test therefore stay off by default (empty filter map / no token).
#   - Can be forced on/off per env by setting the toggle to "on"/"off".
#
# The subscription-filter maps below are only non-empty for prod and staging, so
# the module's log-group + subscription-filter resources still only instantiate
# there; enabling in an env with an empty map is a safe no-op (module deploys the
# Slack secret + Lambda but wires no filters).
#
# Authored, NOT applied (merge-hold + go-decision per #366). Before apply, confirm
# the subscription-filter log-group names still match the live ECS / batch / lambda
# log groups in each env.
# =============================================================================

locals {
  # Log groups to subscribe per env. Empty for dev/sandbox/test.
  cloudwatch_alerting_filters = var.DEPLOYMENT_ENVIRONMENT == "prod" ? {
    "ecs-logs-prod" : "",
    "/aws/batch/job" : "",
    "/aws/lambda/taxon-indexing-eviction-lambda-prod-evict_taxons" : ""
    } : var.DEPLOYMENT_ENVIRONMENT == "staging" ? {
    "ecs-logs-staging" : "",
    "/aws/batch/job" : "",
    "/aws/lambda/taxon-indexing-eviction-lambda-staging-evict_taxons" : ""
  } : {}

  # "auto" => enable only where there is a filter map to wire AND a Slack token
  # is configured. "on"/"off" force it regardless.
  cloudwatch_alerting_enabled = (
    var.enable_cloudwatch_alerting == "on" ? true :
    var.enable_cloudwatch_alerting == "off" ? false :
    (length(local.cloudwatch_alerting_filters) > 0 && var.SLACK_OAUTH_TOKEN_SECRET_NAME != "")
  )
}

module "cloudwatch-alerting" {
  count  = local.cloudwatch_alerting_enabled ? 1 : 0
  source = "./modules/cloudwatch-alerting"

  deployment_environment         = var.DEPLOYMENT_ENVIRONMENT
  log_group_subscription_filters = local.cloudwatch_alerting_filters
  alerts_slack_channel           = var.ALERTS_SLACK_CHANNEL
  alerts_slack_channel_id        = var.ALERTS_SLACK_CHANNEL_ID
  slack_oauth_token_secret_name  = var.SLACK_OAUTH_TOKEN_SECRET_NAME
}
