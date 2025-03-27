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
