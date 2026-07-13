# CZID-447 — toggle for the log-based CloudWatch -> Slack alerting module
# (cloudwatch-alerting.tf).
#
# Declared here (a committed file) rather than in the env-injected, gitignored
# terraform/variables.tf, so it travels with the code.
#
# DEFAULT IS "off" (deliberate, CZID-447). The Slack alerting DESTINATION (channel +
# OAuth token) is a CUSTOMER decision that has not been made yet, and we must NOT route
# CZ ID operational logs to the previous owner's Slack. So this stays hard-off until the
# customer stands up their OWN Slack channel + token secret and someone flips it to "on"
# per env with those customer-owned values. Do not set it to "auto"/"on" until then.
# (Also: the alerting module itself is currently non-functional — its scan-logs-and-alert
# Lambda resource is undefined; see #447.)

variable "enable_cloudwatch_alerting" {
  description = <<-EOT
    Whether to enable the log-based CloudWatch -> Slack alerting module.
      "off" (DEFAULT): force disabled. Keep this until the CUSTOMER's Slack channel +
        a customer-owned OAuth-token secret are configured — never the prior owner's.
      "auto": enable only where there is a non-empty subscription-filter map (prod +
        staging) AND SLACK_OAUTH_TOKEN_SECRET_NAME is set. dev/sandbox/test stay off.
      "on":  force enabled (requires a customer-owned Slack token secret configured).
  EOT
  type        = string
  default     = "off"

  validation {
    condition     = contains(["auto", "on", "off"], var.enable_cloudwatch_alerting)
    error_message = "enable_cloudwatch_alerting must be one of: auto, on, off."
  }
}
