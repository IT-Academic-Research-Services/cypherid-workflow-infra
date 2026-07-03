# CZID-156 — tuning inputs for the pipeline observability alarms
# (cloudwatch-alarms.tf).
#
# Declared here (a committed file) rather than in the env-injected, gitignored
# terraform/variables.tf, so they travel with the code. All have defaults, so no
# wrapper/env change is required to plan.

variable "sfn_execution_duration_threshold_ms" {
  description = "SFN ExecutionTime ceiling (ms) above which the duration alarm fires. Default 6h — a workflow hanging rather than failing outright."
  type        = number
  default     = 21600000
}

variable "sfn_notifications_queue_depth_threshold" {
  description = "Backlog depth on the SFN notification queue above which the depth alarm fires (completions not drained by the app consumer)."
  type        = number
  default     = 100
}

variable "pipeline_alerts_extra_sns_topic_arn" {
  description = <<-EOT
    Optional extra SNS topic ARN to also notify on pipeline alarms, in addition to
    the pipeline-alerts topic created here. PLACEHOLDER for a shared/central alerts
    topic. Empty (default) => only the local pipeline-alerts topic is notified.
  EOT
  type        = string
  default     = ""
}
