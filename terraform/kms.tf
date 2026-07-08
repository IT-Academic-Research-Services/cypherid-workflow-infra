# Customer-managed KMS key for the workflows data tier (CZID-57, encryption-at-rest).
# Replaces the AWS-owned default key so workflow artifacts sit under a key we control + rotate.
# Account root administers the key; consumer IAM policies grant usage (standard baseline).
resource "aws_kms_key" "workflows" {
  description             = "seqtoid workflows data tier (${var.DEPLOYMENT_ENVIRONMENT})"
  enable_key_rotation     = true
  deletion_window_in_days = 30
  policy                  = data.aws_iam_policy_document.workflows_kms.json
}

resource "aws_kms_alias" "workflows" {
  name          = "alias/seqtoid-workflows-${var.DEPLOYMENT_ENVIRONMENT}"
  target_key_id = aws_kms_key.workflows.key_id
}

data "aws_iam_policy_document" "workflows_kms" {
  statement {
    sid       = "AccountRootAdmin"
    actions   = ["kms:*"]
    resources = ["*"]
    principals {
      type        = "AWS"
      identifiers = formatlist("arn:aws:iam::%s:root", var.AWS_ACCOUNT_ID)
    }
  }

  # Allow the CloudWatch Logs service to use this key so the managed lambda log groups
  # (CZID-63) can be encrypted with it. Scoped by encryption context to this account's
  # /aws/lambda/* groups so the grant can't be borrowed to decrypt unrelated log data.
  statement {
    sid = "AllowCloudWatchLogs"
    actions = [
      "kms:Encrypt",
      "kms:Decrypt",
      "kms:ReEncrypt*",
      "kms:GenerateDataKey*",
      "kms:DescribeKey",
    ]
    resources = ["*"]
    principals {
      type        = "Service"
      identifiers = ["logs.${var.AWS_DEFAULT_REGION}.amazonaws.com"]
    }
    condition {
      test     = "ArnLike"
      variable = "kms:EncryptionContext:aws:logs:arn"
      values   = ["arn:aws:logs:${var.AWS_DEFAULT_REGION}:${var.AWS_ACCOUNT_ID}:log-group:/aws/lambda/*"]
    }
  }
}
