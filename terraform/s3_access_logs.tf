# S3 server access logging for the workflows bucket (CZID-60).
# A dedicated, hardened log bucket (private, versioned, lifecycle-expired) receives access logs.
# Uses SSE-S3 (AES256), not the CMK: S3 log *delivery* doesn't support an SSE-KMS CMK on the target
# bucket, so AES256 is the correct choice for a log-destination bucket.

resource "aws_s3_bucket" "workflows_logs" {
  bucket        = "seqtoid-workflows-logs-${var.DEPLOYMENT_ENVIRONMENT}-${var.AWS_ACCOUNT_ID}"
  force_destroy = local.data_force_destroy
}

resource "aws_s3_bucket_public_access_block" "workflows_logs" {
  bucket                  = aws_s3_bucket.workflows_logs.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "workflows_logs" {
  bucket = aws_s3_bucket.workflows_logs.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_versioning" "workflows_logs" {
  bucket = aws_s3_bucket.workflows_logs.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "workflows_logs" {
  depends_on = [aws_s3_bucket_versioning.workflows_logs]
  bucket     = aws_s3_bucket.workflows_logs.id

  rule {
    id     = "expire-access-logs"
    status = "Enabled"
    expiration {
      days = 365
    }
    noncurrent_version_expiration {
      noncurrent_days = 30
    }
  }
}

# Allow S3 server-access-log delivery to write into the log bucket (modern bucket-policy grant,
# scoped to the source bucket + this account).
data "aws_iam_policy_document" "workflows_logs" {
  statement {
    sid       = "S3ServerAccessLogsPolicy"
    actions   = ["s3:PutObject"]
    resources = ["${aws_s3_bucket.workflows_logs.arn}/*"]
    principals {
      type        = "Service"
      identifiers = ["logging.s3.amazonaws.com"]
    }
    condition {
      test     = "ArnLike"
      variable = "aws:SourceArn"
      values   = [aws_s3_bucket.workflows.arn]
    }
    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [tostring(var.AWS_ACCOUNT_ID)]
    }
  }
}

resource "aws_s3_bucket_policy" "workflows_logs" {
  bucket = aws_s3_bucket.workflows_logs.id
  policy = data.aws_iam_policy_document.workflows_logs.json
}

# Point the workflows bucket's access logs at the log bucket.
resource "aws_s3_bucket_logging" "workflows" {
  bucket        = aws_s3_bucket.workflows.id
  target_bucket = aws_s3_bucket.workflows_logs.id
  target_prefix = "s3-access/"
}
