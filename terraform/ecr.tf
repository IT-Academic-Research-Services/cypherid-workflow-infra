locals {
  # TODO: Is "legacy-host-filter" actually unused? If not, add it back in...
  ecr_repository_names = ["amr", "benchmark", "bulk-download", "consensus-genome", "diamond", "host-genome-generation", "index-generation", "long-read-mngs", "minimap2", "phylotree-ng", "short-read-mngs"]
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

  # NOTE (CZID-59, ECR KMS): adding `encryption_configuration { encryption_type = "KMS" }` here
  # would FORCE-REPLACE these repos (ECR encryption is immutable), destroying all pushed images.
  # That needs a migration (re-push / rebuild) and is tracked separately — intentionally NOT done here.
}
