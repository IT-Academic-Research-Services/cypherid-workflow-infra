// Environment Variables
variable "deployment_environment" {
  type        = string
  description = "deployment environment: (test, dev, staging, prod)"
}

// CloudWatch Logs log group subscription filter variables
variable "log_group_subscription_filters" {
  type        = map(any)
  description = "Subscription filters (key: log group name, value: filter expression)"
}

// Slack hook variables
variable "alerts_slack_channel" {
  type        = string
  description = "Slack channel to alert"
}

variable "alerts_slack_channel_id" {
  type        = string
  description = "Id of Slack channel to alert"
}

variable "slack_oauth_token_secret_name" {
  type        = string
  description = "Name of the AWS Secrets Manager secret containing the Slack OAuth token"
}
