locals {
  service_name                   = "idseq-${var.DEPLOYMENT_ENVIRONMENT}-index-generation"
  launch_template_user_data_file = "${path.module}/index_generation_instance_user_data"
  launch_template_user_data_hash = filemd5(local.launch_template_user_data_file)
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

resource "aws_launch_template" "index_generation_launch_template" {
  # checkov:skip=CKV_AWS_341:hop_limit=2 is required for AWS Batch container workloads to reach IMDS (container→host→IMDS = 2 hops). IMDSv2 is still enforced via http_tokens=required. (CZID-57)
  # AWS Batch pins a specific version of the launch template when a compute environment is created.
  # The CE does not support updating this version, and needs replacing (redeploying) if launch template contents change.
  # The launch template resource increments its version when contents change, but the compute environment resource does
  # not recognize this change. We bind the launch template name to user data contents here, so any changes to user data
  # will cause the whole launch template to be replaced, forcing the compute environment to pick up the changes.
  name      = "${local.service_name}-batch-${local.launch_template_user_data_hash}"
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

  dynamic "block_device_mappings" {
    for_each = toset(["f", "g", "h", "i"])

    content {
      device_name = "/dev/sd${block_device_mappings.key}"
      ebs {
        # Lever 1 (platform-overhaul 548): scratch right-sized 64 TB -> ~4 TB.
        # index_generation_instance_user_data RAID0s every /dev/sd? volume into a single /mnt
        # (Docker data-root). Previously 4 x 16384 GB (16 TB) = 64 TB of gp3 that, per the cost
        # brief, cost more per hour (~$7.2) than the instance itself. With PR-1's per-task disk
        # declarations (seqtoid-workflows #16) each phase keeps only its own working set (~4 TB),
        # so 4 x 1024 GB (1 TB) = ~4 TB RAID0 is sufficient. Keeping four devices preserves the
        # RAID0 striping/throughput the user-data script expects. gp3 defaults (3000 IOPS /
        # 125 MB/s per volume) are unchanged; RAID0 across four volumes still parallelizes I/O.
        volume_size           = 1024 # GB; 4 devices x 1024 = ~4 TB scratch (was 16384 = 64 TB)
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

    # Lever 2 (platform-overhaul 548): move the right-sized box onto Graviton (arm64).
    #
    # This supersedes the x86 family choice from Lever 1 (r6i/m6i/c6i). Same rationale as Lever 1 --
    # index generation runs as ONE monolithic Batch job (the SFN `RunEC2` state submits a single job;
    # miniwdl executes every WDL task locally on that one host), so the box only has to fit the PEAK
    # phase (compress, ~384 GB), and a curated multi-family list lets Batch bin-pack onto the smallest
    # instance that satisfies the cpu/memory request (see RunEC2Memory below). The only change here is
    # the CPU architecture: x86 6th-gen -> Graviton3 7th-gen for ~15-40% better price/performance.
    #   r7g - memory-optimized, covers the compress peak (r7g.12xlarge 48/384, r7g.16xlarge 64/512)
    #   m7g - general-purpose, covers the moderate index phase
    #   c7g - compute/IO, covers the small download phase
    # r7g/m7g/c7g are the 1:1 Graviton3 analogues of the r6i/m6i/c6i sizes and match the same
    # vCPU/memory points, so the box-selection logic (RunEC2Memory = 393216 MB) is unchanged.
    #
    # GATING (do NOT apply until both hold):
    #   1. The arm64/multi-arch index-generation image (seqtoid-workflows, index-generation Dockerfile)
    #      is merged and the multi-arch image is published -- an arm64 host cannot pull an x86-only
    #      image. All six tools (ncbi-compress, minimap2, diamond, seqkit, marisa-trie, BLAST+) build
    #      and smoke on linux/arm64; see that PR.
    #   2. A benchmark-equivalence run (IDSEQ_BENCH AUPR >= 0.98) proves the arm64-built indexes match
    #      the x86 baseline. Arch changes are only adopted after the AUPR gate, per the plan.
    #
    # NOTE: this is still one box per run. True per-phase fan-out onto separate right-sized boxes
    # (the plan's "fan the chunked index build out to small spot workers") requires switching the
    # runner to the miniwdl-aws Batch backend so each WDL task becomes its own Batch job -- a later
    # change. This CE list is already forward-compatible with that (the small c7g/m7g sizes are here).
    #
    # BANDWIDTH NOTE: r5n was the network-optimized ("n") choice for the download/upload phases. r7g
    # tops out lower (~12.5-30 Gbps) than r5n (~100 Gbps); acceptable because download is I/O- not
    # network-bound at this scale. If a profiling run shows the download/upload phase is
    # network-starved, add the network-optimized "r7gn" family here.
    instance_type = var.DEPLOYMENT_ENVIRONMENT == "test" ? ["optimal"] : ["r7g", "m7g", "c7g"]

    tags = {
      Name = "${local.service_name}-batch"
    }

    image_id = data.aws_ssm_parameter.idseq_batch_ami.value
    #TODO: Is this needed?
    # ec2_key_pair       = "idseq-${var.DEPLOYMENT_ENVIRONMENT}"
    min_vcpus     = 0
    desired_vcpus = 0
    # Caps total concurrent vCPUs. 96 comfortably hosts the single monolithic runner box
    # (compress peak ~48-64 vCPU on r7g.12xlarge/r7g.16xlarge) with headroom. Raise this when the
    # miniwdl-aws per-task fan-out lands and multiple right-sized boxes run in parallel.
    max_vcpus          = 96
    security_group_ids = [aws_security_group.index_generation.id]

    subnets = length(data.aws_subnets.webservice_subnets) > 0 ? data.aws_subnets.webservice_subnets[0].ids : [for subnet in aws_subnet.idseq : subnet.id]

    type = "EC2"
    # BEST_FIT_PROGRESSIVE (was BEST_FIT): with a single fixed instance type BEST_FIT was fine, but
    # now that instance_type spans several Graviton families Batch must bin-pack each job onto the
    # smallest family/size that fits and progress to the next best type when capacity is short. This
    # remains correct for the r7g/m7g/c7g list. Valid for EC2 compute environments.
    # FOLLOW-UP: this CE bids spot (bid_percentage = 100 + spot fleet role). If it is switched to a
    # true SPOT compute environment (type = "SPOT"), change this to SPOT_PRICE_CAPACITY_OPTIMIZED so
    # Batch draws from the deepest/cheapest Graviton spot pools and minimizes interruptions during the
    # long compression phase -- a separate change, not made here.
    allocation_strategy = "BEST_FIT_PROGRESSIVE"
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

  tags = {
    Name = "${local.service_name}-batch"
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
      # RunEC2Memory / RunEC2Vcpu for the single monolithic index-generation Batch job. MEMORY is
      # the container memory reservation the SFN passes as ContainerOverrides.Memory (RunEC2Memory)
      # -- it is what makes Batch choose (and reserve) the instance, so it co-determines the box
      # together with the CE instance_type list above.
      #
      # Lever 1 (platform-overhaul 548): reduced 480000 -> 393216 MB to match PR-1's profiled
      # compress peak (~384 GB) plus a little host headroom, so Batch bin-packs onto an r6i.12xlarge
      # (48/384) / r6i.16xlarge (64/512) instead of a 768 GB box. 393216 MB = 384 GiB.
      #
      # GATING: the exact right-size is only confirmable by a profiling run. If the compress phase
      # OOMs or Batch cannot place a 393216 MB job on r6i.12xlarge (ECS host reservation eats a few
      # GB), Batch already steps up to the next-larger r6i (r6i.16xlarge, 512 GB) automatically --
      # still far below the old 768 GB box. Re-tune from the profiling run before enabling the
      # scheduled trigger. RunEC2Vcpu is currently advisory: the SFN template overrides only Memory,
      # so vCPU comes from the SWIPE-generated job definition, not this value.
      MEMORY              = "393216"
      VCPU                = "48"
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
