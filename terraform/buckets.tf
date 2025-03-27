resource "aws_s3_bucket" "idseq-public-references" {
  bucket = "idseq-public-references"
  count  = var.DEPLOYMENT_ENVIRONMENT == "prod" ? 1 : 0

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
}

resource "aws_s3_bucket_policy" "idseq-public-references" {
  count = var.DEPLOYMENT_ENVIRONMENT == "prod" ? 1 : 0

  bucket = aws_s3_bucket.idseq-public-references[0].bucket

  policy = templatefile("${path.module}/iam_policy_templates/s3-delegate-access.json", {
    delegated_arns = ["arn:aws:iam::732052188396:root"],
    bucket_name    = aws_s3_bucket.idseq-public-references[0].bucket
  })
}

resource "aws_s3_bucket" "czid-public-references" {
  bucket = "czid-public-references"
  count  = var.DEPLOYMENT_ENVIRONMENT == "prod" ? 1 : 0

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
  tags = merge(local.common_tags, {
    public_read_justification = "CZ ID bioinformatics references derived from open data",
    bucket_contents           = "Bioinformatics reference databases"
  })
}

resource "aws_s3_bucket_policy" "czid-public-references" {
  count = var.DEPLOYMENT_ENVIRONMENT == "prod" ? 1 : 0

  bucket = aws_s3_bucket.czid-public-references[0].bucket

  policy = templatefile("${path.module}/iam_policy_templates/s3-delegate-access.json", {
    delegated_arns = ["arn:aws:iam::732052188396:root"],
    bucket_name    = aws_s3_bucket.czid-public-references[0].bucket
  })
}

resource "aws_s3_bucket" "idseq-prod-system-test" {
  bucket = "idseq-prod-system-test"
  count  = var.DEPLOYMENT_ENVIRONMENT == "prod" ? 1 : 0
}
