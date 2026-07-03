# =============================================================================
# CZID-156 — pipeline observability: SFN / Batch / DLQ alarms.
# -----------------------------------------------------------------------------
# The pipeline is Step-Functions-driven (the swipe module). cloudwatch-dashboards.tf
# already charts the SFN execution metrics; this file adds the missing first-class
# ALARMS on the failure modes, wired to a pipeline-alerts SNS topic:
#
#   - SFN executions failed / timed out / aborted   (AWS/States, per state machine)
#   - SFN execution duration high                    (AWS/States ExecutionTime)
#   - Batch failed jobs                              (index-generation queue)
#   - SFN notification / DLQ queue depth             (AWS/SQS, the swipe web queue)
#
# SFN state machine ARNs and the notification queue ARN come straight from the
# swipe module outputs (module.swipe.sfn_arns / .sfn_notification_queue_arns), so
# the alarms track whatever workflows swipe provisions with no hard-coded ARNs.
#
# Authored, NOT applied. Thresholds are conservative starting points; tune per env.
# Alarm actions fan out to aws_sns_topic.pipeline_alerts, plus any extra ARN
# supplied via var.pipeline_alerts_extra_sns_topic_arn (placeholder for a shared
# alerts topic).
# =============================================================================

locals {
  pipeline_alarm_actions = concat(
    [aws_sns_topic.pipeline_alerts.arn],
    var.pipeline_alerts_extra_sns_topic_arn == "" ? [] : [var.pipeline_alerts_extra_sns_topic_arn],
  )

  # Map of workflow-name => state machine ARN, from swipe.
  sfn_arns = module.swipe.sfn_arns

  # The web notification queue ARN -> derive the queue name for the SQS dimension.
  sfn_web_queue_arn  = try(module.swipe.sfn_notification_queue_arns["web"], "")
  sfn_web_queue_name = local.sfn_web_queue_arn == "" ? "" : element(split(":", local.sfn_web_queue_arn), length(split(":", local.sfn_web_queue_arn)) - 1)
}

#trivy:ignore:AVD-AWS-0136 SNS holds only CloudWatch-alarm metadata (no sensitive data); the AWS-managed SNS key satisfies encryption-at-rest, so a CMK is unwarranted.
resource "aws_sns_topic" "pipeline_alerts" {
  name              = "idseq-${var.DEPLOYMENT_ENVIRONMENT}-pipeline-alerts"
  kms_master_key_id = "alias/aws/sns" # encrypt at rest (CKV_AWS_26); AWS-managed SNS key for alarm metadata
}

# --- SFN: executions failed --------------------------------------------------
resource "aws_cloudwatch_metric_alarm" "sfn_executions_failed" {
  for_each = local.sfn_arns

  alarm_name        = "idseq-${var.DEPLOYMENT_ENVIRONMENT}-sfn-${each.key}-executions-failed"
  alarm_description = "Step Functions ${each.key} execution failures — pipeline ${var.DEPLOYMENT_ENVIRONMENT}."

  namespace   = "AWS/States"
  metric_name = "ExecutionsFailed"
  dimensions  = { StateMachineArn = each.value }

  statistic           = "Sum"
  period              = 300
  evaluation_periods  = 1
  threshold           = 0
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"

  alarm_actions = local.pipeline_alarm_actions
  ok_actions    = local.pipeline_alarm_actions
}

# --- SFN: executions timed out -----------------------------------------------
resource "aws_cloudwatch_metric_alarm" "sfn_executions_timed_out" {
  for_each = local.sfn_arns

  alarm_name        = "idseq-${var.DEPLOYMENT_ENVIRONMENT}-sfn-${each.key}-executions-timed-out"
  alarm_description = "Step Functions ${each.key} executions timed out — pipeline ${var.DEPLOYMENT_ENVIRONMENT}."

  namespace   = "AWS/States"
  metric_name = "ExecutionsTimedOut"
  dimensions  = { StateMachineArn = each.value }

  statistic           = "Sum"
  period              = 300
  evaluation_periods  = 1
  threshold           = 0
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"

  alarm_actions = local.pipeline_alarm_actions
  ok_actions    = local.pipeline_alarm_actions
}

# --- SFN: executions aborted -------------------------------------------------
resource "aws_cloudwatch_metric_alarm" "sfn_executions_aborted" {
  for_each = local.sfn_arns

  alarm_name        = "idseq-${var.DEPLOYMENT_ENVIRONMENT}-sfn-${each.key}-executions-aborted"
  alarm_description = "Step Functions ${each.key} executions aborted — pipeline ${var.DEPLOYMENT_ENVIRONMENT}."

  namespace   = "AWS/States"
  metric_name = "ExecutionsAborted"
  dimensions  = { StateMachineArn = each.value }

  statistic           = "Sum"
  period              = 300
  evaluation_periods  = 1
  threshold           = 0
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"

  alarm_actions = local.pipeline_alarm_actions
}

# --- SFN: execution duration high --------------------------------------------
# ExecutionTime is milliseconds. Default 6h ceiling catches a workflow that hangs
# instead of failing outright; tune per workflow SLO.
resource "aws_cloudwatch_metric_alarm" "sfn_execution_duration_high" {
  for_each = local.sfn_arns

  alarm_name        = "idseq-${var.DEPLOYMENT_ENVIRONMENT}-sfn-${each.key}-execution-duration-high"
  alarm_description = "Step Functions ${each.key} execution duration exceeded the SLO ceiling — pipeline ${var.DEPLOYMENT_ENVIRONMENT}."

  namespace   = "AWS/States"
  metric_name = "ExecutionTime"
  dimensions  = { StateMachineArn = each.value }

  statistic           = "Maximum"
  period              = 300
  evaluation_periods  = 1
  threshold           = var.sfn_execution_duration_threshold_ms
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"

  alarm_actions = local.pipeline_alarm_actions
}

# --- Batch: failed jobs (index-generation queue this repo owns) --------------
resource "aws_cloudwatch_metric_alarm" "batch_index_generation_failed_jobs" {
  alarm_name        = "idseq-${var.DEPLOYMENT_ENVIRONMENT}-batch-index-generation-failed-jobs"
  alarm_description = "AWS Batch failed jobs on the index-generation queue — pipeline ${var.DEPLOYMENT_ENVIRONMENT}."

  namespace   = "AWS/Batch"
  metric_name = "FailedJobs"
  dimensions  = { JobQueue = aws_batch_job_queue.index_generation_job_queue.name }

  statistic           = "Sum"
  period              = 300
  evaluation_periods  = 1
  threshold           = 0
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"

  alarm_actions = local.pipeline_alarm_actions
  ok_actions    = local.pipeline_alarm_actions
}

# --- Pipeline health dashboard (SFN outcomes + Batch/SQS) --------------------
# Complements the existing IDseq-pipeline-runs dashboard (run counts/timings)
# with a failure-focused health view driven by the same swipe outputs.
locals {
  pipeline_health_sfn_widgets = [
    for wf, arn in local.sfn_arns : {
      type   = "metric"
      width  = 12
      height = 6
      properties = {
        title  = "SFN ${wf} — outcomes"
        region = var.AWS_DEFAULT_REGION
        view   = "timeSeries"
        metrics = [
          ["AWS/States", "ExecutionsSucceeded", "StateMachineArn", arn],
          ["AWS/States", "ExecutionsFailed", "StateMachineArn", arn],
          ["AWS/States", "ExecutionsTimedOut", "StateMachineArn", arn],
          ["AWS/States", "ExecutionsAborted", "StateMachineArn", arn],
        ]
      }
    }
  ]

  pipeline_health_batch_widget = {
    type   = "metric"
    width  = 12
    height = 6
    properties = {
      title  = "Batch index-generation — jobs"
      region = var.AWS_DEFAULT_REGION
      view   = "timeSeries"
      metrics = [
        ["AWS/Batch", "SubmittedJobs", "JobQueue", aws_batch_job_queue.index_generation_job_queue.name],
        ["AWS/Batch", "FailedJobs", "JobQueue", aws_batch_job_queue.index_generation_job_queue.name],
      ]
    }
  }

  pipeline_health_queue_widgets = local.sfn_web_queue_name == "" ? [] : [
    {
      type   = "metric"
      width  = 12
      height = 6
      properties = {
        title  = "SFN notification queue — depth"
        region = var.AWS_DEFAULT_REGION
        view   = "timeSeries"
        metrics = [
          ["AWS/SQS", "ApproximateNumberOfMessagesVisible", "QueueName", local.sfn_web_queue_name],
          ["AWS/SQS", "ApproximateAgeOfOldestMessage", "QueueName", local.sfn_web_queue_name],
        ]
      }
    }
  ]

  pipeline_health_widgets = concat(
    local.pipeline_health_sfn_widgets,
    [local.pipeline_health_batch_widget],
    local.pipeline_health_queue_widgets,
  )
}

resource "aws_cloudwatch_dashboard" "pipeline_health" {
  dashboard_name = "IDseq-pipeline-health-${var.DEPLOYMENT_ENVIRONMENT}"
  dashboard_body = jsonencode({ widgets = local.pipeline_health_widgets })
}

# --- SQS: SFN notification / DLQ depth ---------------------------------------
# The swipe web queue backs SFN completion notifications; a growing backlog means
# the app-side consumer (Shoryuken) is not draining completions. In dev this queue
# is configured with a dead-letter queue (swipe sqs_queues.web.dead_letter).
resource "aws_cloudwatch_metric_alarm" "sfn_notifications_queue_depth" {
  count = local.sfn_web_queue_name == "" ? 0 : 1

  alarm_name        = "idseq-${var.DEPLOYMENT_ENVIRONMENT}-sfn-notifications-queue-depth"
  alarm_description = "SFN notification queue backlog — completions not being drained by the app consumer — pipeline ${var.DEPLOYMENT_ENVIRONMENT}."

  namespace   = "AWS/SQS"
  metric_name = "ApproximateNumberOfMessagesVisible"
  dimensions  = { QueueName = local.sfn_web_queue_name }

  statistic           = "Maximum"
  period              = 300
  evaluation_periods  = 3
  threshold           = var.sfn_notifications_queue_depth_threshold
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"

  alarm_actions = local.pipeline_alarm_actions
  ok_actions    = local.pipeline_alarm_actions
}
