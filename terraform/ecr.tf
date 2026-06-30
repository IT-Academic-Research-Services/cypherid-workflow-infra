locals {
  # TODO: Is "legacy-host-filter" actually unused? If not, add it back in...
  ecr_repository_names = ["amr", "benchmark", "bulk-download", "consensus-genome", "diamond", "host-genome-generation", "index-generation", "long-read-mngs", "minimap2", "phylotree-ng", "short-read-mngs"]

  # CZID-59 (ECR KMS at-rest). ECR `encryption_configuration` is an IMMUTABLE attribute: enabling it
  # on an existing repo FORCE-REPLACES the repo and destroys all pushed images. So it is only safe to
  # enable where the repos are created fresh (greenfield). On LIVE envs (dev/staging) turning this on
  # is a re-push MIGRATION (rebuild + push images under the new repo) and is gated as Bucket B.
  #
  # Greenfield envs opt in via this list; everything else stays unchanged (plan no-op, no replacement).
  # The apply on any listed env still requires the mandatory `terraform plan`-review to confirm the repos
  # are genuinely being created (not replaced) before proceeding.
  ecr_cmk_greenfield_envs = ["prod"]
  ecr_encrypt_with_cmk    = contains(local.ecr_cmk_greenfield_envs, var.DEPLOYMENT_ENVIRONMENT)
}

resource "aws_ecr_repository" "workflow-repositories" {
  for_each             = toset(local.ecr_repository_names)
  name                 = each.key
  image_tag_mutability = "MUTABLE"
  # DATA-1 (CZID-31): only allow terraform to delete a non-empty repo in throwaway envs.
  force_delete = local.data_force_destroy

  image_scanning_configuration {
    scan_on_push = true
  }

  # CZID-59: customer-managed KMS encryption-at-rest, enabled only on greenfield envs (see local above)
  # because the attribute is immutable. Reuses the workflows data-tier key (kms.tf).
  dynamic "encryption_configuration" {
    for_each = local.ecr_encrypt_with_cmk ? [1] : []
    content {
      encryption_type = "KMS"
      kms_key         = aws_kms_key.workflows.arn
    }
  }
}
