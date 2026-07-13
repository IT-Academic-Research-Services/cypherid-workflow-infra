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
      # CZID-41: aws 5.x (>= 5.31 knows the python3.12 lambda runtime the
      # chalice codegen now emits). The generated chalice.tf.json modules
      # hardcode "< 5"; scripts/package_lambda.py relaxes that to "< 6" so
      # terraform's provider-version intersection allows this pin.
      version = "~> 5.31"
    }
  }
}
