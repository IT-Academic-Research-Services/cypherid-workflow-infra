resource "aws_iam_role" "taxon_indexing_concurrency_manager_role" {
  name = "taxon-indexing-concurrency-manager-${var.deployment_environment}"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action = "sts:AssumeRole"
      Effect = "Allow"
      Sid    = ""
      Principal = {
        Service = "lambda.amazonaws.com"
      }
    }]
  })
}

resource "aws_iam_role_policy" "taxon_indexing_concurrency_manager_role" {
  name = "taxon-indexing-concurrency-manager-rolePolicy"
  role = aws_iam_role.taxon_indexing_concurrency_manager_role.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "logs:CreateLogGroup",
          "logs:CreateLogStream",
          "logs:PutLogEvents"
        ]
        Resource = "arn:aws:logs:*:*:*"
      },
      {
        Effect = "Allow"
        Action = [
          "cloudwatch:PutMetricData",
          "iam:ListAccountAliases"
        ]
        Resource = "*"
      },
      {
        Effect = "Allow"
        Action = [
          "ec2:CreateNetworkInterface",
          "ec2:DescribeNetworkInterfaces",
          "ec2:DetachNetworkInterface",
          "ec2:DeleteNetworkInterface"
        ]
        Resource = "*"
      },
      {
        Effect = "Allow"
        Action = [
          "lambda:InvokeFunction"
        ],
        Resource = var.index_taxon_lambda_arn
      }
    ]
  })
}

# NOTE (CZID-63 follow-up): a managed CloudWatch log group for this lambda was reverted. It was
# declared for bounded retention + CMK encryption, but in dev Lambda had already auto-created the
# implicit `/aws/lambda/taxon-indexing-concurrency-manager-dev` group (no retention, no KMS), so
# every apply failed with ResourceAlreadyExistsException -- which blocked deploying this lambda at
# all. Adopting the existing group needs `terraform import`, and a declarative `import` block only
# takes effect in a FULL plan; this repo deploys with `-target` (which skips import blocks), and a
# full dev apply is unsafe (a large, destroy-carrying backlog). So the managed group is removed here
# to unblock lambda deploys. The lambda still logs to the implicit auto-created group. Re-adopt the
# group with retention + the workflows CMK once the dev backlog is reconciled (via a full apply that
# processes an import block, or a one-off `terraform import`). Tracked as a follow-up.

resource "aws_lambda_function" "taxon_indexing_concurrency_manager" {
  function_name    = "taxon-indexing-concurrency-manager-${var.deployment_environment}"
  runtime          = "nodejs20.x"
  handler          = "app.handler"
  memory_size      = 512
  timeout          = 900
  source_code_hash = filebase64sha256("${path.module}/deployment.zip")
  filename         = "${path.module}/deployment.zip"
  environment {
    variables = {
      INDEX_TAXONS_FUNCTION_NAME = var.index_taxon_lambda_name
    }
  }
  role = aws_iam_role.taxon_indexing_concurrency_manager_role.arn
}
