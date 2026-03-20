locals {
  # TODO: Where else to put these, possibly env-specific, configurations?
  s3_bucket_workflows         = "cypherid-samples-deleteme"
  s3_bucket_public_references = "seqtoid-public-references"
}

# TODO: Create one bucket per environment? Or one bucket per version?
#  Either way, we need to have the bucket owned by Terraform in some Environment; currently it's manually created and managed
data "aws_s3_bucket" "public-references" {
  bucket = local.s3_bucket_public_references
}

# Added this here, because it is a bucket, and we need to keep track of it somewhere!
data "aws_s3_bucket" "workflows" {
  bucket = local.s3_bucket_workflows
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
