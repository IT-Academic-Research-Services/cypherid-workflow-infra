locals {
  # TODO: Where else to put these, possibly env-specific, configurations?
  # s3_bucket_workflows         = "cypherid-samples-deleteme"
  s3_bucket_workflows         = "seqtoid-workflows-${var.DEPLOYMENT_ENVIRONMENT}-${var.AWS_ACCOUNT_ID}"
  s3_bucket_public_references = "seqtoid-public-references"

  # DATA-1 (CZID-31): allow terraform to destroy data resources only in throwaway envs;
  # protect the shared/long-lived envs (staging/prod) from a silent destroy/replace data loss.
  data_force_destroy = contains(["dev", "sandbox"], var.DEPLOYMENT_ENVIRONMENT)
}

# TODO: Create one bucket per environment? Or one bucket per version?
#  Either way, we need to have the bucket owned by Terraform in some Environment; currently it's manually created and managed
data "aws_s3_bucket" "public-references" {
  bucket = local.s3_bucket_public_references
}

resource "aws_s3_bucket" "workflows" {
  bucket        = local.s3_bucket_workflows
  force_destroy = local.data_force_destroy
}

# CZID-57 / CZID-60: encrypt the workflows bucket at rest with the customer-managed key
# (see kms.tf) instead of the AWS-owned default. Bucket keys cut KMS request cost.
resource "aws_s3_bucket_server_side_encryption_configuration" "workflows" {
  bucket = aws_s3_bucket.workflows.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm     = "aws:kms"
      kms_master_key_id = aws_kms_key.workflows.arn
    }
    bucket_key_enabled = true
  }
}

# Block all public access. The workflows bucket is private (the bucket policy
# below grants read only to the account root), so this just enforces it at the
# bucket level — defense-in-depth against an accidental public ACL/policy.
# (CZID-57 / Trivy AWS-0086–0093, Checkov CKV2_AWS_6.)
resource "aws_s3_bucket_public_access_block" "workflows" {
  bucket                  = aws_s3_bucket.workflows.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_versioning" "workflows" {
  bucket = aws_s3_bucket.workflows.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "workflows" {
  depends_on = [aws_s3_bucket_versioning.workflows]
  bucket     = aws_s3_bucket.workflows.id

  rule {
    id = "default"
    noncurrent_version_transition {
      noncurrent_days = 30
      storage_class   = "DEEP_ARCHIVE"
    }

    noncurrent_version_expiration {
      noncurrent_days = 60
    }

    status = "Enabled"
  }
}

# resource "aws_s3_bucket_acl" "workflows" {
#   bucket = aws_s3_bucket.workflows.id
#   acl    = "private"
# }

data "aws_iam_policy_document" "workflows-bucket" {
  statement {
    sid = "ReadAccess"
    actions = [
      "s3:ListBucket*",
      "s3:GetObject*"
    ]
    resources = [
      aws_s3_bucket.workflows.arn,
      "${aws_s3_bucket.workflows.arn}/*"
    ]
    principals {
      type        = "AWS"
      identifiers = formatlist("arn:aws:iam::%s:root", var.AWS_ACCOUNT_ID)
      # type        = "*"
      # identifiers = ["*"]
    }
    effect = "Allow"
  }
}

resource "aws_s3_bucket_policy" "workflows" {
  bucket = aws_s3_bucket.workflows.id
  policy = data.aws_iam_policy_document.workflows-bucket.json
}

# resource "aws_s3_bucket" "cypherid-public-references" {
#   bucket = "cypherid-public-references-dev-941377154785"   # TODO: Unhardcode this
#   bucket = "seqtoid-public-references${local.s3_suffix}"
#   count  = var.DEPLOYMENT_ENVIRONMENT == "sandbox" ? 1 : 0 # TODO: Should be owned by "prod" and not "sandbox" !!!
#
#   versioning {
#     enabled = true
#   }
#
#   lifecycle_rule {
#     enabled = true
#
#     noncurrent_version_transition {
#       days          = 30
#       storage_class = "DEEP_ARCHIVE"
#     }
#
#     noncurrent_version_expiration {
#       days = 60
#     }
#   }
#
#   dynamic "lifecycle_rule" {
#     for_each = [
#       "alignment_data/2017",
#       "alignment_data/2018",
#       "alignment_data/2019",
#       "alignment_indexes/2017",
#       "alignment_indexes/2018",
#       "alignment_indexes/2019"
#     ]
#
#     content {
#       enabled = true
#       prefix  = lifecycle_rule.value
#       transition {
#         days          = 30
#         storage_class = "DEEP_ARCHIVE"
#       }
#     }
#   }
#   tags = merge(local.common_tags, {
#     env = "dev" # TODO: Fix
#     public_read_justification = "CZ ID bioinformatics references derived from open data",
#     bucket_contents           = "Bioinformatics reference databases"
#   })
# }
#
# resource "aws_s3_bucket_policy" "cypherid-public-references" {
#   count = var.DEPLOYMENT_ENVIRONMENT == "sandbox" ? 1 : 0 # TODO: Should be owned by "prod" and not "sandbox" !!!
#
#   bucket = aws_s3_bucket.cypherid-public-references[0].bucket
#
#   policy = templatefile("${path.module}/iam_policy_templates/s3-delegate-access.json", {
#     delegated_arns = [
#       "arn:aws:iam::491013321714:root", # dev
#       "arn:aws:iam::941377154785:root", # staging
#       "arn:aws:iam::283694049553:root", # prod
#       "arn:aws:iam::030998640247:root"
#     ],
#     bucket_name = aws_s3_bucket.cypherid-public-references[0].bucket
#   })
# }

# resource "aws_s3_bucket" "czid-public-references" {
#   bucket = "czid-public-references"
#   count  = var.DEPLOYMENT_ENVIRONMENT == "prod" ? 1 : 0
#
#   versioning {
#     enabled = true
#   }
#
#   lifecycle_rule {
#     enabled = true
#
#     noncurrent_version_transition {
#       days          = 30
#       storage_class = "DEEP_ARCHIVE"
#     }
#
#     noncurrent_version_expiration {
#       days = 60
#     }
#   }
#
#   dynamic "lifecycle_rule" {
#     for_each = [
#       "alignment_data/2017",
#       "alignment_data/2018",
#       "alignment_data/2019",
#       "alignment_indexes/2017",
#       "alignment_indexes/2018",
#       "alignment_indexes/2019"
#     ]
#
#     content {
#       enabled = true
#       prefix  = lifecycle_rule.value
#       transition {
#         days          = 30
#         storage_class = "DEEP_ARCHIVE"
#       }
#     }
#   }
#   tags = merge(local.common_tags, {
#     public_read_justification = "CZ ID bioinformatics references derived from open data",
#     bucket_contents           = "Bioinformatics reference databases"
#   })
# }
#
# #Removed because we don't need to make the bucket public for now, and shouldn't need to delegate access to another account
# resource "aws_s3_bucket_policy" "czid-public-references" {
#   count = var.DEPLOYMENT_ENVIRONMENT == "prod" ? 1 : 0
#
#   bucket = aws_s3_bucket.czid-public-references[0].bucket
#
#   policy = templatefile("${path.module}/iam_policy_templates/s3-delegate-access.json", {
#     delegated_arns = ["arn:aws:iam::732052188396:root"],
#     bucket_name    = aws_s3_bucket.czid-public-references[0].bucket
#   })
# }

# resource "aws_s3_bucket" "idseq-prod-system-test" {
#   bucket = "idseq-prod-system-test"
#   count  = var.DEPLOYMENT_ENVIRONMENT == "prod" ? 1 : 0
# }
