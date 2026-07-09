# NOTE: the Lambda functions referenced below as
#   aws_lambda_function.scan_logs_and_alert (main.tf) and
#   aws_lambda_function.custom_invocation (outputs.tf)
# are intentionally NOT declared in this .tf file. They are code-generated into
# this module directory as chalice.tf.json by `make package-lambdas`
# (scripts/package_lambda.py), which runs `chalice package --pkg-format terraform`
# on the Chalice app in lambdas/cloudwatch-alerting/. Chalice registers each
# handler as an aws_lambda_function resource keyed by its handler name, i.e.
# aws_lambda_function.scan_logs_and_alert and aws_lambda_function.custom_invocation
# (function_name "cloudwatch-alerting-<stage>-<handler>"). CI (validate.yml) and
# the deploy/plan Make targets all run that codegen before tofu init/validate/apply,
# so these references resolve at build time.
#
# Consequence: running `tofu validate` on this module WITHOUT first running
# `make package-lambdas` reports "Reference to undeclared resource
# aws_lambda_function ..." -- that is the missing codegen, NOT a bug in this
# module. Do not "fix" it by repointing to data.aws_lambda_function lookups:
# chalice.tf.json always emits these as managed resources in this same module,
# so a data lookup would read a function that this apply is creating and fail on
# first apply. The TF-vs-Chalice ownership boundary is: Chalice owns the Lambda
# resources (via generated chalice.tf.json), this file owns the surrounding
# CloudWatch/Secrets/SNS wiring.

# in case some log groups don't exist when we apply we should create them
#   this may happen if the log group doesn't exist because it has
#   no entries yet

# use the log group name as the prefix to get any log groups with that name
data "aws_cloudwatch_log_groups" "existing_groups" {
  for_each              = var.log_group_subscription_filters
  log_group_name_prefix = each.key
}

resource "aws_cloudwatch_log_group" "new_groups" {
  for_each = toset([
    for k, v in var.log_group_subscription_filters :
    # create log groups if we didn't find one with their name
    k if length(data.aws_cloudwatch_log_groups.existing_groups[k]) == 0
  ])
  name         = each.key
  skip_destroy = true
}

resource "aws_secretsmanager_secret" "slack_oauth_token" {
  count = var.deployment_environment == "test" ? 0 : 1

  name                    = var.slack_oauth_token_secret_name
  recovery_window_in_days = 0
}

resource "aws_cloudwatch_log_subscription_filter" "idseq_alerting" {
  for_each        = var.log_group_subscription_filters
  name            = "idseq-${var.deployment_environment}-${each.key}"
  log_group_name  = each.key
  filter_pattern  = each.value
  destination_arn = aws_lambda_function.scan_logs_and_alert.arn

  # wait to create any missing log groups before deploying
  depends_on = [resource.aws_cloudwatch_log_group.new_groups]
}

resource "aws_lambda_permission" "idseq_alerting_cloudwatch" {
  statement_id  = "AllowExecutionFromCloudWatch"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.scan_logs_and_alert.function_name
  principal     = "logs.amazonaws.com"
}

resource "aws_sns_topic" "aws_heatmap_topic" {
  count = var.deployment_environment == "test" ? 1 : 0
  name  = "${var.deployment_environment}-idseq-heatmap-topic"
}
