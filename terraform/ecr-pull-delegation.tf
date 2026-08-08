# Cross-account PULL delegation for the workflow image repos — the ECR analog of the CZID-362 S3
# read delegation on the workflows bucket (see buckets.tf). Empty by default (= current behavior:
# repos are pullable only within their own account), so this is a byte-identical no-op until an ARN
# is supplied per env.
#
# Purpose: the dev->staging promotion (promote-to-staging) needs the STAGING promote role to PULL the
# published workflow images from THIS (dev) account's ECR, alongside the S3 bundle read it already
# gets via WORKFLOWS_BUCKET_DELEGATED_READ_ARNS. Least-privilege: pull-only verbs, only the specific
# role ARNs that must read. `ecr:GetAuthorizationToken` is account-scoped and lives on the CALLER's
# own IAM policy (the staging role), NOT here — a repository policy cannot grant it.

variable "WORKFLOW_ECR_DELEGATED_PULL_ARNS" {
  description = "Extra IAM principal ARNs granted cross-account PULL on the workflow ECR repos (e.g. the staging promote role). Empty by default (own-account pull only). Least-privilege: list only the specific principals that must pull this account's workflow images."
  type        = list(string)
  default     = []
}

data "aws_iam_policy_document" "workflow_repo_pull_delegation" {
  count = length(var.WORKFLOW_ECR_DELEGATED_PULL_ARNS) > 0 ? 1 : 0
  statement {
    sid    = "CrossAccountPull"
    effect = "Allow"
    principals {
      type        = "AWS"
      identifiers = var.WORKFLOW_ECR_DELEGATED_PULL_ARNS
    }
    actions = [
      "ecr:GetDownloadUrlForLayer",
      "ecr:BatchGetImage",
      "ecr:BatchCheckLayerAvailability",
      "ecr:DescribeImages",
      "ecr:DescribeRepositories",
    ]
  }
}

# Attach to every workflow repo (short-read-mngs, minimap2, ...). Gated on a non-empty ARN list so the
# default produces NO resources (plan no-op), mirroring the CZID-362 S3 dynamic-statement gate.
resource "aws_ecr_repository_policy" "workflow_repo_pull_delegation" {
  for_each   = length(var.WORKFLOW_ECR_DELEGATED_PULL_ARNS) > 0 ? aws_ecr_repository.workflow-repositories : {}
  repository = each.value.name
  policy     = data.aws_iam_policy_document.workflow_repo_pull_delegation[0].json
}
