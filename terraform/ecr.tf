locals {
  ecr_repository_names = ["consensus-genome", "diamond"]
}

resource "aws_ecr_repository" "cypherid-consensus-genome" {
  for_each             = toset(local.ecr_repository_names)
  name                 = each.key
  image_tag_mutability = "MUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }

  tags = local.common_tags
}