# Single source of truth for the Terraform version floor + provider version
# constraints for this repo (CZID-169). Both root modules use it: the repo-root
# config (alongside main.tf's backend block) and the test/ localstack mock,
# which references it via the test/versions.tf -> ../versions.tf symlink. Bump a
# provider here once instead of editing main.tf and test/mock.tf separately
# (e.g. the aws v4 -> v5 work in CZID-41). The backend block is intentionally
# NOT here so the test mock stays on local state.
terraform {
  required_version = ">= 1.10" # >= 1.10 for native S3 state locking (use_lockfile)
  required_providers {
    aws = {
      version = "~> 4.54"
    }
  }
}
