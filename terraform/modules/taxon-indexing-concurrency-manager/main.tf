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

# CloudWatch log group for the concurrency-manager lambda (CZID-63). Declared explicitly
# for bounded retention + encryption-at-rest instead of the implicit, never-expiring group
# Lambda auto-creates. Created before the function (depends_on) so it writes into this group.
# In an env where the implicit group already exists, import it once before the first apply.
resource "aws_cloudwatch_log_group" "taxon_indexing_concurrency_manager" {
  #checkov:skip=CKV_AWS_338:90-day retention (var.log_retention_in_days) is the deliberate cost/policy choice for this lambda log group; CKV_AWS_338 wants >=1 year. Logs are KMS-encrypted via the workflows CMK (var.log_kms_key_arn).
  name              = "/aws/lambda/taxon-indexing-concurrency-manager-${var.deployment_environment}"
  retention_in_days = var.log_retention_in_days
  kms_key_id        = var.log_kms_key_arn
}

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

  # Ensure the managed log group exists before the function can auto-create an implicit one.
  depends_on = [aws_cloudwatch_log_group.taxon_indexing_concurrency_manager]
}
