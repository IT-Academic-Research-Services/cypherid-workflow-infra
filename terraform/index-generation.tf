locals {
  service_name                   = "idseq-${var.DEPLOYMENT_ENVIRONMENT}-index-generation"
  launch_template_user_data_file = "${path.module}/index_generation_instance_user_data"
  launch_template_user_data_hash = filemd5(local.launch_template_user_data_file)
}

data "aws_ssm_parameter" "idseq_batch_ami" {
  # NOTE: this conditional is because moto errors on creating ssm parameters that begin with aws or ssm
  name = "/${var.DEPLOYMENT_ENVIRONMENT == "test" ? "mock-aws" : "aws"}/service/ecs/optimized-ami/amazon-linux-2/recommended/image_id"
}

data "aws_vpc" "webservice_vpc" {
  count = var.DEPLOYMENT_ENVIRONMENT == "test" ? 0 : 1

  tags = {
    service = "cloud-env"
    env     = var.DEPLOYMENT_ENVIRONMENT == "dev" ? "sandbox" : var.DEPLOYMENT_ENVIRONMENT
  }
}

data "aws_subnets" "webservice_subnets" {
  count = var.DEPLOYMENT_ENVIRONMENT == "test" ? 0 : 1

  filter {
    name   = "tag:service"
    values = ["cloud-env"]
  }

  filter {
    name   = "tag:env"
    values = [var.DEPLOYMENT_ENVIRONMENT == "dev" ? "sandbox" : var.DEPLOYMENT_ENVIRONMENT]
  }

  filter {
    name   = "tag:Name"
    values = ["*-public-*"]
  }
}

resource "aws_security_group" "index_generation" {
  name   = "index-generation-${var.DEPLOYMENT_ENVIRONMENT}"
  vpc_id = length(data.aws_vpc.webservice_vpc) > 0 ? data.aws_vpc.webservice_vpc[0].id : aws_vpc.idseq.id
  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

resource "aws_launch_template" "index_generation_launch_template" {
  # AWS Batch pins a specific version of the launch template when a compute environment is created.
  # The CE does not support updating this version, and needs replacing (redeploying) if launch template contents change.
  # The launch template resource increments its version when contents change, but the compute environment resource does
  # not recognize this change. We bind the launch template name to user data contents here, so any changes to user data
  # will cause the whole launch template to be replaced, forcing the compute environment to pick up the changes.
  name      = "${local.service_name}-batch-${local.launch_template_user_data_hash}"
  user_data = filebase64(local.launch_template_user_data_file)
  tags      = local.common_tags

  # NOTE[JH]: This setting makes IMDSv2 required. Any software that needs to talk to the metadata service
  # needs to do so using the v2 endpoint.
  # https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/configuring-instance-metadata-service.html

  image_id = data.aws_ssm_parameter.idseq_batch_ami.value
  metadata_options {
    http_endpoint               = "enabled"
    http_tokens                 = "required"
    http_put_response_hop_limit = 2
  }

  dynamic "block_device_mappings" {
    for_each = toset(["f", "g", "h", "i"])

    content {
      device_name = "/dev/sd${block_device_mappings.key}"
      ebs {
        volume_size           = 16384 # size in GB, maximum size for EBS volume
        encrypted             = true
        delete_on_termination = true
      }
    }
  }
}

resource "aws_batch_compute_environment" "index_generation_compute_environment" {
  compute_environment_name_prefix = "${local.service_name}-"

  compute_resources {
    instance_role = aws_iam_instance_profile.idseq_batch_main.arn

    /** The i3.16xlarge series was selected because index generation requires a lot of memory,
      * of fast storage for scratch space, and a lot of bandwidth for downloading
      * source files and uploading indexes. i3.16xlarge instances have decent bandwidth, NVME
      * memory, and high storage.
      */
    instance_type = var.DEPLOYMENT_ENVIRONMENT == "test" ? ["optimal"] : ["r5n.24xlarge"]

    tags = merge(local.common_tags, {
      Name = "${local.service_name}-batch"
    })

    image_id           = data.aws_ssm_parameter.idseq_batch_ami.value
    ec2_key_pair       = "idseq-${var.DEPLOYMENT_ENVIRONMENT}"
    min_vcpus          = 0
    desired_vcpus      = 0
    max_vcpus          = 96 // 1 r5n.24xlarge
    security_group_ids = [aws_security_group.index_generation.id]

    subnets = length(data.aws_subnets.webservice_subnets) > 0 ? data.aws_subnets.webservice_subnets[0].ids : [for subnet in aws_subnet.idseq : subnet.id]

    type                = "EC2"
    allocation_strategy = "BEST_FIT"
    bid_percentage      = 100
    spot_iam_fleet_role = aws_iam_role.idseq_batch_spot_fleet_service_role.arn

    launch_template {
      launch_template_name = aws_launch_template.index_generation_launch_template.name
    }
  }

  service_role = aws_iam_role.idseq_batch_service_role.arn
  type         = "MANAGED"

  lifecycle {
    create_before_destroy = true
    ignore_changes = [
      compute_resources[0].desired_vcpus,
    ]
  }
}

resource "aws_batch_job_queue" "index_generation_job_queue" {
  name     = local.service_name
  state    = "ENABLED"
  priority = 10
  compute_environments = [
    aws_batch_compute_environment.index_generation_compute_environment.arn,
  ]
}

data "archive_file" "lambda_archive" {
  type             = "zip"
  source_dir       = "${path.module}/start_index_generation_lambda_src"
  output_file_mode = "0666"
  output_path      = "${path.module}/index-generation-lambda.zip"
}

resource "aws_iam_role" "start_index_generation_lambda" {

  name = "start_index_generation-lambda-${var.DEPLOYMENT_ENVIRONMENT}"

  assume_role_policy = jsonencode({
    Version = "2012-10-17",
    Statement = [
      {
        Action : "sts:AssumeRole",
        Effect : "Allow",
        Principal : {
          Service : "lambda.amazonaws.com",
        },
      },
    ],
  })

  tags = local.common_tags
}

resource "aws_iam_role_policy" "start_index_generation_lambda" {

  name = "start_index_generation-lambda-${var.DEPLOYMENT_ENVIRONMENT}"
  role = aws_iam_role.start_index_generation_lambda.id

  policy = jsonencode({
    Version : "2012-10-17",
    Statement : [
      {
        Effect : "Allow",
        Action : [
          "states:StartExecution",
        ],
        Resource : module.swipe.sfn_arns["index-generation"],
      },
      {
        Effect : "Allow",
        Action : [
          "s3:ListBucket",
        ],
        Resource : "arn:aws:s3:::${var.DEPLOYMENT_ENVIRONMENT == "prod" ? "czid-public-references" : "idseq-database"}",
      },
      {
        Effect : "Allow",
        Action : [
          "logs:CreateLogGroup",
          "logs:CreateLogStream",
          "logs:PutLogEvents",
        ],
        Resource : "arn:aws:logs:*:*:*",
    }]
  })
}

resource "aws_lambda_function" "start_index_generation" {
  function_name    = "idseq-start_index_generation-${var.DEPLOYMENT_ENVIRONMENT}"
  runtime          = "python3.8"
  handler          = "main.start_index_generation"
  memory_size      = 256
  timeout          = 600
  source_code_hash = data.archive_file.lambda_archive.output_sha
  filename         = data.archive_file.lambda_archive.output_path

  role = aws_iam_role.start_index_generation_lambda.arn
  tags = local.common_tags

  environment {
    variables = {
      DEPLOYMENT_ENVIRONMENT            = var.DEPLOYMENT_ENVIRONMENT
      INDEX_GENERATION_SFN_ARN          = module.swipe.sfn_arns["index-generation"]
      INDEX_GENERATION_WORKFLOW_VERSION = "v2.4.4"
      AWS_ACCOUNT_ID                    = var.AWS_ACCOUNT_ID
      MEMORY                            = "480000"
      VCPU                              = "60"
      BUCKET                            = var.DEPLOYMENT_ENVIRONMENT == "prod" ? "czid-public-references" : "idseq-database"
    }
  }
}

// disabled because index generation script is broken
// 
// resource "aws_lambda_permission" "start_index_generation_eventbridge" {
//   statement_id  = "AllowExecutionFromCloudWatch"
//   action        = "lambda:InvokeFunction"
//   function_name = aws_lambda_function.start_index_generation.function_name
//   principal     = "events.amazonaws.com"
//   source_arn    = aws_cloudwatch_event_rule.start_index_generation.arn
// }
//
// resource "aws_cloudwatch_event_rule" "start_index_generation" {
//   name        = "czid-${var.DEPLOYMENT_ENVIRONMENT}-index-generation-schedule"
//   description = "Triggers index generation at 2 AM on the 1st, 7thm and 14th of each month for dev, staging, and prod"
//   schedule_expression = lookup({
//     "staging" : "cron(0 2 7 * ? *)",
//     "prod" : "cron(0 2 14 * ? *)",
//   }, var.DEPLOYMENT_ENVIRONMENT, "cron(0 2 1 * ? *)")
// }
//
// resource "aws_cloudwatch_event_target" "start_generation" {
//   rule      = aws_cloudwatch_event_rule.start_index_generation.name
//   target_id = "automated-index-generation"
//   arn       = aws_lambda_function.start_index_generation.arn
// }
