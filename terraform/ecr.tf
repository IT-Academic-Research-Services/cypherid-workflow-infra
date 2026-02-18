locals {
  ecr_repository_names = ["amr", "benchmark", "bulk-download", "consensus-genome", "diamond", "host-genome-generation", "index-generation", "legacy-host-filter", "long-read-mngs", "minimap2", "phylotree-ng", "short-read-mngs"]
}

resource "aws_ecr_repository" "workflow-repositories" {
  for_each             = toset(local.ecr_repository_names)
  name                 = each.key
  image_tag_mutability = "MUTABLE"
  force_delete         = true

  image_scanning_configuration {
    scan_on_push = true
  }
}
