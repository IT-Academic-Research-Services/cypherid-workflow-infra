data "aws_kms_alias" "parameter_store" {
  count = var.DEPLOYMENT_ENVIRONMENT == "test" ? 0 : 1

  name = "alias/parameter_store_key"
}

resource "aws_iam_policy" "idseq_batch_main_job" {
  name = "idseq-${var.DEPLOYMENT_ENVIRONMENT}-batch-job"
  policy = templatefile("${path.module}/iam_policy_templates/batch_job.json", {
    AWS_DEFAULT_REGION     = var.AWS_DEFAULT_REGION,
    AWS_ACCOUNT_ID         = var.AWS_ACCOUNT_ID,
    DEPLOYMENT_ENVIRONMENT = var.DEPLOYMENT_ENVIRONMENT,
    PARAMETER_KMS_KEY_ARN  = length(data.aws_kms_alias.parameter_store) > 0 ? data.aws_kms_alias.parameter_store[0].target_key_arn : "",
  })
}

resource "aws_iam_role" "idseq_batch_main_job" {
  name = "idseq-${var.DEPLOYMENT_ENVIRONMENT}-batch-job"
  assume_role_policy = templatefile("${path.module}/iam_policy_templates/trust_policy.json", {
    trust_services = ["ecs-tasks"]
  })
  tags = local.common_tags
}

resource "aws_iam_role_policy_attachment" "idseq_batch_main_job" {
  role       = aws_iam_role.idseq_batch_main_job.name
  policy_arn = aws_iam_policy.idseq_batch_main_job.arn
}

resource "aws_iam_role_policy_attachment" "idseq_batch_main_job_ecr_readonly" {
  role       = aws_iam_role.idseq_batch_main_job.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonEC2ContainerRegistryReadOnly"
}
