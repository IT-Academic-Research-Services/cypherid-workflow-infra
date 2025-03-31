resource "aws_ecr_repository" "cypherid-consensus-genome" {
  name                 = "consensus-genome"
  image_tag_mutability = "MUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }
}