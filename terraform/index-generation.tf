locals {
  service_name = "idseq-${var.DEPLOYMENT_ENVIRONMENT}-index-generation"

  # Per-stage boxes each format+mount a single right-sized gp3 scratch volume (Lever 1,
  # Track A) instead of the old 64 TB 4-volume RAID0 the monolith needed. One shared
  # user-data file drives all stage launch templates; its hash is bound into every stage
  # launch-template name so a user-data change forces the compute environments to replace
  # and pick it up (AWS Batch pins the launch-template version at CE creation).
  launch_template_user_data_file = "${path.module}/index_generation_stage_instance_user_data"
  launch_template_user_data_hash = filemd5(local.launch_template_user_data_file)

  # Index-generation is now a multi-stage SWIPE pipeline: each phase runs as its own Batch
  # job on its own right-sized compute environment + queue (mirroring short-read-mngs),
  # replacing the single monolithic r5n.24xlarge CE. Sizing seeds are from the Part-3
  # fan-out design / PR-1 per-task numbers; confirm against one profiling run before prod.
  #
  #   download        IO-bound download; small on-demand box, small scratch.
  #   compress        long single ncbi-compress task; r6i on-demand, ~4 TB scratch.
  #                   ON-DEMAND on purpose: a spot reclaim on this multi-hour un-checkpointed
  #                   task restarts the whole rebuild (the reason the on-demand CE fix landed).
  #   index_spot      minimap2/diamond index build on SPOT -- interruption-tolerant, cheap.
  #   index_ondemand  on-demand fallback the SFN Index stage falls back to on a spot reclaim.
  #
  # In the moto test env everything collapses to on-demand "optimal" (spot fleet + specific
  # families are not modelled by moto), matching how the old single CE behaved under test.
  index_generation_stages = {
    download = {
      instance_types = ["c6i.2xlarge"] # 8 vCPU / 16 GB
      max_vcpus      = 8
      scratch_gb     = 500
      provisioning   = "EC2"
    }
    compress = {
      instance_types = ["r6i.12xlarge"] # 48 vCPU / 384 GB
      max_vcpus      = 48
      scratch_gb     = 4096
      provisioning   = "EC2"
    }
    index_spot = {
      instance_types = ["r6i.4xlarge", "r6i.8xlarge", "r6i.12xlarge"]
      max_vcpus      = 192
      scratch_gb     = 2048
      provisioning   = "SPOT"
    }
    index_ondemand = {
      instance_types = ["r6i.4xlarge", "r6i.8xlarge", "r6i.12xlarge"]
      max_vcpus      = 192
      scratch_gb     = 2048
      provisioning   = "EC2"
    }
  }
}

# Retention (days) for the lambda CloudWatch log groups this repo manages (CZID-63).
# Applied to the start_index_generation group here and passed to the concurrency-manager
# module so all managed lambda logs expire on the same schedule instead of never.
variable "lambda_log_retention_in_days" {
  type        = number
  default     = 90
  description = "CloudWatch Logs retention in days for lambda log groups managed by this repo."
}

data "aws_ssm_parameter" "idseq_batch_ami" {
  # NOTE: this conditional is because moto errors on creating ssm parameters that begin with aws or ssm
  name = "/${var.DEPLOYMENT_ENVIRONMENT == "test" ? "mock-aws" : "aws"}/service/ecs/optimized-ami/amazon-linux-2/recommended/image_id"
}

data "aws_vpc" "webservice_vpc" {
  count = var.DEPLOYMENT_ENVIRONMENT == "test" ? 0 : 1

  tags = {
    service = "cloud-env"
    env     = var.DEPLOYMENT_ENVIRONMENT
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
    values = [var.DEPLOYMENT_ENVIRONMENT]
  }

  filter {
    name   = "tag:Name"
    values = ["*-public-*"]
  }
}

resource "aws_security_group" "index_generation" {
  # CZID-56: same rationale as aws_security_group.idseq — public-subnet Batch tier with no VPC
  # endpoints must reach AWS service endpoints AND download reference data (NCBI etc.) from arbitrary
  # public hosts over the IGW, all over HTTP/HTTPS. Destination stays 0.0.0.0/0 (arbitrary reference
  # sources) until the VPC endpoints architecture lands (CZID-352, design:
  # VPC-ENDPOINTS-ARCHITECTURE-2026-06-29.md). Egress is narrowed off "-1"/all-ports to HTTPS + HTTP
  # + DNS, which removes arbitrary-port outbound and clears CKV_AWS_382; Trivy AWS-0104 (0.0.0.0/0
  # destination) is kept + baselined in .trivyignore with this justification.
  name   = "index-generation-${var.DEPLOYMENT_ENVIRONMENT}"
  vpc_id = length(data.aws_vpc.webservice_vpc) > 0 ? data.aws_vpc.webservice_vpc[0].id : aws_vpc.idseq.id
  egress {
    description = "HTTPS to AWS endpoints / reference data sources"
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }
  egress {
    description = "HTTP for reference data / mirror pulls"
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }
  egress {
    description = "DNS (UDP)"
    from_port   = 53
    to_port     = 53
    protocol    = "udp"
    cidr_blocks = ["0.0.0.0/0"]
  }
  egress {
    description = "DNS (TCP)"
    from_port   = 53
    to_port     = 53
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

# One launch template per stage (Lever 1, Track A). Each attaches a SINGLE right-sized gp3
# scratch volume -- no more 64 TB RAID0. The user-data hash is bound into the name so a
# user-data change replaces the template and forces the compute environment to pick it up
# (AWS Batch pins the launch-template version at CE creation and cannot update it in place).
resource "aws_launch_template" "index_generation" {
  # checkov:skip=CKV_AWS_341:hop_limit=2 is required for AWS Batch container workloads to reach IMDS (container→host→IMDS = 2 hops). IMDSv2 is still enforced via http_tokens=required. (CZID-57)
  for_each = local.index_generation_stages

  name      = "${local.service_name}-${each.key}-batch-${local.launch_template_user_data_hash}"
  user_data = filebase64(local.launch_template_user_data_file)

  # NOTE[JH]: This setting makes IMDSv2 required. Any software that needs to talk to the metadata service
  # needs to do so using the v2 endpoint.
  # https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/configuring-instance-metadata-service.html

  image_id = data.aws_ssm_parameter.idseq_batch_ami.value
  metadata_options {
    http_endpoint               = "enabled"
    http_tokens                 = "required"
    http_put_response_hop_limit = 2
  }

  # Single per-stage scratch volume (gp3), sized to that phase's working set only.
  block_device_mappings {
    device_name = "/dev/sdf"
    ebs {
      volume_size           = each.value.scratch_gb
      volume_type           = "gp3"
      encrypted             = true
      delete_on_termination = true
    }
  }
}

# One compute environment per stage. SPOT stages set the spot-only params (type = "SPOT",
# bid_percentage, spot_iam_fleet_role); on-demand stages leave them null -- setting spot
# params on a type = "EC2" CE is exactly the latent misconfig that made the old CE silently
# run on-demand, so we only set them when the CE is genuinely SPOT.
resource "aws_batch_compute_environment" "index_generation" {
  for_each                        = local.index_generation_stages
  compute_environment_name_prefix = "${local.service_name}-${each.key}-"

  compute_resources {
    instance_role = aws_iam_instance_profile.idseq_batch_main.arn

    # In the moto test env, collapse to on-demand "optimal": spot fleet + specific instance
    # families are not modelled by moto (matches how the old single CE behaved under test).
    instance_type = var.DEPLOYMENT_ENVIRONMENT == "test" ? ["optimal"] : each.value.instance_types

    tags = {
      Name = "${local.service_name}-${each.key}-batch"
    }

    image_id           = data.aws_ssm_parameter.idseq_batch_ami.value
    min_vcpus          = 0
    desired_vcpus      = 0
    max_vcpus          = each.value.max_vcpus
    security_group_ids = [aws_security_group.index_generation.id]

    subnets = length(data.aws_subnets.webservice_subnets) > 0 ? data.aws_subnets.webservice_subnets[0].ids : [for subnet in aws_subnet.idseq : subnet.id]

    type = var.DEPLOYMENT_ENVIRONMENT == "test" ? "EC2" : each.value.provisioning
    allocation_strategy = (
      var.DEPLOYMENT_ENVIRONMENT != "test" && each.value.provisioning == "SPOT"
      ? "SPOT_CAPACITY_OPTIMIZED"
      : "BEST_FIT"
    )
    bid_percentage = (
      var.DEPLOYMENT_ENVIRONMENT != "test" && each.value.provisioning == "SPOT" ? 100 : null
    )
    spot_iam_fleet_role = (
      var.DEPLOYMENT_ENVIRONMENT != "test" && each.value.provisioning == "SPOT"
      ? aws_iam_role.idseq_batch_spot_fleet_service_role.arn
      : null
    )

    launch_template {
      launch_template_name = aws_launch_template.index_generation[each.key].name
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

  tags = {
    Name = "${local.service_name}-${each.key}-batch"
  }
}

# One queue per stage, 1:1 with the per-stage compute environments above. The multi-stage
# SFN template (sfn_templates/index-generation.yml) routes each phase to its queue via the
# extra_template_vars wired in swipe.tf; the Index stage uses index_spot with index_ondemand
# as its on-demand fallback.
resource "aws_batch_job_queue" "index_generation" {
  for_each = local.index_generation_stages

  name                 = "${local.service_name}-${each.key}"
  state                = "ENABLED"
  priority             = 10
  compute_environments = [aws_batch_compute_environment.index_generation[each.key].arn]
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
        Resource : "arn:aws:s3:::seqtoid-public-references", # TODO: aws_s3_bucket.cypherid-public-references[0].arn
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

# CloudWatch log group for the start_index_generation lambda (CZID-63). Declared
# explicitly so logs have a bounded retention and encryption-at-rest instead of the
# implicit, never-expiring, AWS-owned-key group Lambda auto-creates on first invoke.
# The group is created before the lambda (see depends_on below) so the function writes
# into this managed group. In an env where the implicit group already exists, import it
# once (terraform import) before the first apply.
resource "aws_cloudwatch_log_group" "start_index_generation" {
  #checkov:skip=CKV_AWS_338:90-day retention (var.lambda_log_retention_in_days) is the deliberate cost/policy choice for these lambda log groups; CKV_AWS_338 wants >=1 year. Logs are KMS-encrypted via the workflows CMK below (CZID-63).
  name              = "/aws/lambda/idseq-start_index_generation-${var.DEPLOYMENT_ENVIRONMENT}"
  retention_in_days = var.lambda_log_retention_in_days
  # Reuse the workflows customer-managed key (CZID-57). CloudWatch Logs usage of the key
  # is granted in kms.tf. The key policy dependency is implicit via this reference.
  kms_key_id = aws_kms_key.workflows.arn
}

resource "aws_lambda_function" "start_index_generation" {
  function_name    = "idseq-start_index_generation-${var.DEPLOYMENT_ENVIRONMENT}"
  runtime          = "python3.12"
  handler          = "main.start_index_generation"
  memory_size      = 256
  timeout          = 600
  source_code_hash = data.archive_file.lambda_archive.output_sha
  filename         = data.archive_file.lambda_archive.output_path

  role = aws_iam_role.start_index_generation_lambda.arn

  # Ensure the managed log group exists before the function can auto-create an implicit one.
  depends_on = [aws_cloudwatch_log_group.start_index_generation]

  environment {
    variables = {
      DEPLOYMENT_ENVIRONMENT            = var.DEPLOYMENT_ENVIRONMENT
      INDEX_GENERATION_SFN_ARN          = module.swipe.sfn_arns["index-generation"]
      INDEX_GENERATION_WORKFLOW_VERSION = "v2.4.4" # Why is this hardcoded, and the most recent seems to be v2.4.8
      AWS_ACCOUNT_ID                    = var.AWS_ACCOUNT_ID
      # Per-stage container memory (MB) for the multi-stage pipeline (Lever 1, Track A).
      # Replaces the single MEMORY/VCPU override of the old monolith. VCPU is now set by
      # each stage's compute-environment instance family, not a container override.
      DOWNLOAD_MEMORY     = "14000"  # c6i.2xlarge (16 GB), IO-bound download
      COMPRESS_MEMORY     = "380000" # r6i.12xlarge (384 GB), ncbi-compress
      INDEX_SPOT_MEMORY   = "128000" # index build on spot
      INDEX_EC2_MEMORY    = "250000" # index build on the on-demand fallback
      BUCKET              = data.aws_s3_bucket.public-references.bucket
      S3_WORKFLOWS_BUCKET = aws_s3_bucket.workflows.bucket
    }
  }
}

// TODO: disabled because index generation script is broken
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
