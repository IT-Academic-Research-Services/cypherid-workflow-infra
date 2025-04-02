locals {
    s3_suffix = var.DEPLOYMENT_ENVIRONMENT == "prod" ? "-${var.AWS_ACCOUNT_ID}" : "-${var.DEPLOYMENT_ENVIRONMENT}-${var.AWS_ACCOUNT_ID}"
}

resource "aws_s3_bucket" "cypherid-public-references" {
  bucket = "cypherid-public-references${local.s3_suffix}"

  versioning {
    enabled = true
  }

  lifecycle_rule {
    enabled = true

    noncurrent_version_transition {
      days          = 30
      storage_class = "DEEP_ARCHIVE"
    }

    noncurrent_version_expiration {
      days = 60
    }
  }

  dynamic "lifecycle_rule" {
    for_each = [
      "alignment_data/2017",
      "alignment_data/2018",
      "alignment_data/2019",
      "alignment_indexes/2017",
      "alignment_indexes/2018",
      "alignment_indexes/2019"
    ]

    content {
      enabled = true
      prefix  = lifecycle_rule.value
      transition {
        days          = 30
        storage_class = "DEEP_ARCHIVE"
      }
    }
  }
  tags = {
    public_read_justification = "CZ ID bioinformatics references derived from open data",
    bucket_contents           = "Bioinformatics reference databases"
  }
}

resource "aws_s3_bucket_policy" "cypherid-public-references" {
  bucket = aws_s3_bucket.cypherid-public-references.bucket

  policy = templatefile("${path.module}/iam_policy_templates/s3-delegate-access.json", {
    delegated_arns = ["arn:aws:iam::941377154785:root"],
    bucket_name    = aws_s3_bucket.cypherid-public-references.bucket
  })
}

//TODO Assuming we do not need this
resource "aws_s3_bucket" "idseq-prod-system-test" {
  bucket = "idseq-prod-system-test"
  count  = var.DEPLOYMENT_ENVIRONMENT == "prod" ? 1 : 0
}
