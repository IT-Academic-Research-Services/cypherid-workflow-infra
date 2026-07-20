# Per-account reference bucket name (generate-once -> replicate prerequisite).
#
# The reference (NT/NR taxon index) bucket used to be a single, hardcoded,
# globally-unique name "seqtoid-public-references". A global-unique S3 name can
# exist in exactly ONE account, so it collides with the program rule that each
# env is self-sufficient in its OWN account (no cross-account providers, no one
# shared bucket read across accounts). To replicate byte-identical index
# artifacts INTO each env, every env needs its own uniquely-named reference
# bucket -- mirroring how s3_bucket_workflows is already per-account.
#
# This variable lets each env supply its own name WITHOUT breaking the live dev
# path: the default is empty, which resolves to the legacy global name below, so
# a `terraform plan` with the var unset is byte-identical to before (no drift,
# nothing destroyed). Envs migrate one at a time by (1) creating + seeding their
# own bucket out-of-band, (2) setting this var to that name, (3) applying. See
# LEVER1-GENERATE-ONCE-REPLICATE-DESIGN.md for the full migration + replication
# flow. NOTE: index-generation.tf still hardcodes the legacy ARN in one IAM
# statement; that must be repointed to this local as part of the same migration
# (tracked separately -- that file is owned by the CE spot-params change).
variable "PUBLIC_REFERENCES_BUCKET_NAME" {
  description = "Override for the per-account reference (taxon index) bucket name. Empty (default) resolves to the legacy global name 'seqtoid-public-references' so existing envs are unchanged. Per-account envs should set this to a unique name, recommended 'seqtoid-public-references-<env>-<account-id>'."
  type        = string
  default     = ""
}

locals {
  # TODO: Where else to put these, possibly env-specific, configurations?
  # s3_bucket_workflows         = "cypherid-samples-deleteme"
  s3_bucket_workflows = "seqtoid-workflows-${var.DEPLOYMENT_ENVIRONMENT}-${var.AWS_ACCOUNT_ID}"

  # Recommended per-account name for envs that adopt their own reference bucket.
  # Not applied automatically (that would change the live data-source lookup and
  # break the current shared bucket); an env opts in by setting
  # var.PUBLIC_REFERENCES_BUCKET_NAME. Kept here as the canonical pattern so all
  # envs converge on the same shape once migrated.
  s3_bucket_public_references_per_account = "seqtoid-public-references-${var.DEPLOYMENT_ENVIRONMENT}-${var.AWS_ACCOUNT_ID}"

  # Effective name: explicit override wins; otherwise the legacy global name so
  # the current dev/staging/prod path is unchanged (byte-identical plan).
  s3_bucket_public_references = var.PUBLIC_REFERENCES_BUCKET_NAME != "" ? var.PUBLIC_REFERENCES_BUCKET_NAME : "seqtoid-public-references"

  # DATA-1 (CZID-31): allow terraform to destroy data resources only in throwaway envs;
  # protect the shared/long-lived envs (staging/prod) from a silent destroy/replace data loss.
  data_force_destroy = contains(["dev", "sandbox"], var.DEPLOYMENT_ENVIRONMENT)
}

# TODO: Create one bucket per environment? Or one bucket per version?
#  Either way, we need to have the bucket owned by Terraform in some Environment; currently it's manually created and managed.
#  This stays a data source (not a TF-owned resource) on purpose: the reference
#  bucket is large and live, and converting it to a managed resource risks a
#  destroy/recreate of many TB of taxon indexes. Per-account TF ownership is a
#  later, deliberately-scoped apply (see LEVER1-GENERATE-ONCE-REPLICATE-DESIGN.md).
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

# CZID-362 (#362 / WBS 20033): optional cross-account read delegation for the
# per-account WDL workflows bucket. Empty by default (= current behavior: the
# bucket grants read only to its OWN account root). This replaces the old
# hardcoded/stale CZI account IDs (732052188396 / 941377154785 / etc.) that were
# commented out below — supply the specific reader ARNs per env instead.
#
# D5 (each env self-sufficient in its own account): a delegation is only needed
# if a DIFFERENT account must read this account's workflow outputs (e.g. a
# central taxon-indexing / benchmarking account). Keep it least-privilege: pass
# the specific account-root or role ARNs that actually need read, nothing wider.
#
# NOTE: this does NOT touch the shared seqtoid-public-references (taxon) bucket —
# that bucket is a data source here (manually created, not TF-owned), so its
# policy cannot be managed from this stack without importing it (a risky change
# on a live shared bucket the pipeline reads — tracked as the Bucket B apply,
# out of scope for this authoring).
variable "WORKFLOWS_BUCKET_DELEGATED_READ_ARNS" {
  description = "Extra IAM principal ARNs (e.g. arn:aws:iam::<account>:root) granted cross-account read on the per-account workflows bucket. Empty by default (own-account read only). Least-privilege: list only the specific principals that must read this account's workflow outputs."
  type        = list(string)
  default     = []
}

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

  # CZID-362: cross-account read delegation, gated on a non-empty ARN list so the
  # default (empty) produces byte-identical policy JSON to before — no drift.
  dynamic "statement" {
    for_each = length(var.WORKFLOWS_BUCKET_DELEGATED_READ_ARNS) > 0 ? [1] : []
    content {
      sid = "CrossAccountReadAccess"
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
        identifiers = var.WORKFLOWS_BUCKET_DELEGATED_READ_ARNS
      }
      effect = "Allow"
    }
  }
}

resource "aws_s3_bucket_policy" "workflows" {
  bucket = aws_s3_bucket.workflows.id
  policy = data.aws_iam_policy_document.workflows-bucket.json
}
