resource "aws_cloudwatch_dashboard" "main" {
  dashboard_name = "IDseq-pipeline-runs-${var.DEPLOYMENT_ENVIRONMENT}"

  dashboard_body = templatefile("${path.module}/cloudwatch_dashboard_templates/pipeline_runs.json", {
    AWS_DEFAULT_REGION     = var.AWS_DEFAULT_REGION,
    AWS_ACCOUNT_ID         = var.AWS_ACCOUNT_ID,
    DEPLOYMENT_ENVIRONMENT = var.DEPLOYMENT_ENVIRONMENT,
  })
}
