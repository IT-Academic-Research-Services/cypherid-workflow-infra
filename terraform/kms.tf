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

  # SMP-1810: the workflow publisher (GitHub-OIDC role czid-<env>-gh-actions-workflows-build)
  # uploads the WDL bundle to the SSE-KMS workflows bucket. A put_object into that bucket needs
  # kms:GenerateDataKey on this CMK or it 403s with
  #   "no identity-based policy allows the kms:GenerateDataKey action"
  # which is exactly how the v0.7.16 long-read publish failed (image reached ECR, bundle did not).
  # The grant lives HERE in the key policy rather than on the role's identity policy on purpose:
  # the gh-actions-* identities are CI-managed and DENYed to the tf-apply role, so an identity-policy
  # edit plans green then fails post-merge. Naming the account root as the principal with an
  # aws:PrincipalArn condition keeps this mirror-safe across all four envs -- it names no absent
  # principal, so it applies cleanly where the publisher role does not exist (only dev publishes;
  # staging/prod receive the bundle via promote-to-staging, not this role).
  statement {
    sid = "AllowWorkflowsPublisherSSEKMS"
    actions = [
      "kms:GenerateDataKey*",
      "kms:Encrypt",
      "kms:Decrypt", # large bundles upload multipart, which re-reads
      "kms:DescribeKey",
    ]
    resources = ["*"]
    principals {
      type        = "AWS"
      identifiers = formatlist("arn:aws:iam::%s:root", var.AWS_ACCOUNT_ID)
    }
    condition {
      test     = "ArnLike"
      variable = "aws:PrincipalArn"
      values   = ["arn:aws:iam::${var.AWS_ACCOUNT_ID}:role/czid-${var.DEPLOYMENT_ENVIRONMENT}-gh-actions-workflows-build"]
    }
  }
}
