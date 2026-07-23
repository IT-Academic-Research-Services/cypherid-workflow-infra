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
  #   compress        long single ncbi-compress task; on-demand, ~4 TB scratch.
  #                   ON-DEMAND on purpose: a spot reclaim on this multi-hour un-checkpointed
  #                   task restarts the whole rebuild (the reason the on-demand CE fix landed).
  #   index_spot      minimap2/diamond index build on SPOT -- interruption-tolerant, cheap.
  #   index_ondemand  on-demand fallback the SFN Index stage falls back to on a spot reclaim.
  #
  # In the moto test env everything collapses to on-demand "optimal" (spot fleet + specific
  # families are not modelled by moto), matching how the old single CE behaved under test.
  #
  # ARCHITECTURE TOGGLE (Lever 2, platform-overhaul 548). Each stage carries BOTH its x86
  # (Track A default / fallback) and its 1:1 Graviton3 (arm64) analogue; var.use_graviton
  # picks which set the compute environments use. The vCPU/memory/scratch/provisioning
  # targets are architecture-independent and identical across the two families, so only the
  # CPU architecture changes -- reverting to x86 is a one-line flip of var.use_graviton back
  # to false. Graviton is HELD/GATED (see var.use_graviton and the AMI note below): default
  # stays x86 until the arm64 image publish + arm64 AUPR >= 0.98 gates pass.
  #
  # x86 -> Graviton3 analogues (same vCPU/GiB point):
  #   download   c6i.2xlarge (8/16)             -> m7g.2xlarge  (8/32)
  #   compress   r6i.12xlarge (48/384)          -> r7g.12xlarge (48/384)
  #   index      r6i.{4,8,12}xlarge (16..48 / 128..384) -> r7g.{4,8,12}xlarge (same)
  index_generation_stages_base = {
    # DOWNLOAD SPLIT (platform-overhaul 799). The old single `download` stage ran
    # update_blastdb.pl + blastdbcmd -out <db>.fsa for core_nt AND full nr AND the taxonomy
    # files on ONE 8-vCPU box sharing ONE scratch volume. That serialized nt behind nr (nr ran
    # ~7.4h, nt then pended "insufficient resources on 1 node") and, worse, nr's nr.fsa filled
    # the shared volume so core_nt failed with "Need 269326843136 bytes, only 144753012736
    # available" (run index-generation-core-nt-s3-192600). Splitting into three per-DATABASE
    # stages -- each its own compute environment + queue (the for_each below) and its OWN
    # right-sized scratch volume -- lets nt, nr and taxonomy download CONCURRENTLY on separate
    # boxes with isolated disks. Download wall-clock collapses from (taxonomy + nr + nt) to
    # max(taxonomy, nr, nt). Per-DB failure is also isolated: with call_cache=true (swipe.tf)
    # a re-run skips the succeeded DB stages and re-runs only the failed one.
    #
    # These SUPERSEDE the single `download` stage. `download` is retained (below) until the
    # SFN template + start_index_generation lambda routing switch lands (799 step 2, see
    # deploy/../DESIGN or the ticket); at that point `download` is removed. Additive for now so
    # nothing that still references the `download` queue breaks.
    #
    # Same 8-vCPU box as the proven single-stage download; only scratch differs, sized to each
    # DB's working set (compressed volumes + uncompressed .fsa) with headroom. gp3 is cheap and
    # the stage is IO-bound. Right-size cores after a profiling run if nr extraction is the long
    # pole (matches this file's "confirm against one profiling run" ethos).
    download_taxonomy = {
      instance_types_x86      = ["c6i.2xlarge"] # 8 vCPU / 16 GB
      instance_types_graviton = ["m7g.2xlarge"] # 8 vCPU / 32 GB (Graviton3)
      max_vcpus               = 8
      # accession2taxid (nucl_gb/nucl_wgs/pdb/prot.FULL ~23.6GB compressed) + taxdump; the
      # decompressed working set is the long pole here (prot.FULL). 512 GB is ample.
      scratch_gb   = 512
      provisioning = "EC2"
    }
    download_nt = {
      instance_types_x86      = ["c6i.2xlarge"]
      instance_types_graviton = ["m7g.2xlarge"]
      max_vcpus               = 8
      # core_nt: compressed BLAST volumes (~269 GB) + core_nt.fsa. 1.5 TB isolated volume.
      scratch_gb   = 1536
      provisioning = "EC2"
    }
    download_nr = {
      instance_types_x86      = ["c6i.2xlarge"]
      instance_types_graviton = ["m7g.2xlarge"]
      max_vcpus               = 8
      # nr is the largest: compressed volumes + full nr.fsa. 2 TB isolated volume (was the DB
      # that exhausted the shared 500 GB / left only 134.8 GiB for core_nt).
      scratch_gb   = 2048
      provisioning = "EC2"
    }
    # RETAINED until the routing switch (799 step 2) moves the SFN off it, then delete.
    download = {
      instance_types_x86      = ["c6i.2xlarge"] # 8 vCPU / 16 GB
      instance_types_graviton = ["m7g.2xlarge"] # 8 vCPU / 32 GB (Graviton3)
      max_vcpus               = 8
      # The Download stage runs update_blastdb.pl (compressed BLAST db volumes) THEN
      # blastdbcmd -entry all -out <db>.fsa for BOTH nt/core_nt AND full nr on the same box.
      # The first real core_nt+nr pull needed ~733 GB (compressed dbs + both uncompressed
      # fasta dumps); the original 500 GB filled up mid-download ("Need 732963945407 bytes,
      # only 253963251712 available"). 2 TB gives headroom for NR/core_nt growth and matches
      # the index stages. IO-bound, so the bigger gp3 volume is cheap.
      scratch_gb   = 2048
      provisioning = "EC2"
    }
    compress = {
      instance_types_x86      = ["r6i.12xlarge"] # 48 vCPU / 384 GB
      instance_types_graviton = ["r7g.12xlarge"] # 48 vCPU / 384 GB (Graviton3)
      # Fan-out (800): CompressNR and CompressNT run CONCURRENTLY (Phase-2 lanes), both on
      # this one compress compute environment. Each ncbi-compress job needs the whole 48-vCPU
      # box, so max_vcpus must fit BOTH at once (2 x 48 = 96) -- at 48 they would serialize
      # and silently lose the compress parallelism the fan-out exists for. Each lane still
      # gets its own r6i.12xlarge node + its own 4 TB scratch (isolated, no shared-disk #798).
      max_vcpus    = 96
      scratch_gb   = 4096
      provisioning = "EC2"
    }
    index_spot = {
      instance_types_x86      = ["r6i.4xlarge", "r6i.8xlarge", "r6i.12xlarge"]
      instance_types_graviton = ["r7g.4xlarge", "r7g.8xlarge", "r7g.12xlarge"]
      max_vcpus               = 192
      scratch_gb              = 2048
      provisioning            = "SPOT"
    }
    index_ondemand = {
      instance_types_x86      = ["r6i.4xlarge", "r6i.8xlarge", "r6i.12xlarge"]
      instance_types_graviton = ["r7g.4xlarge", "r7g.8xlarge", "r7g.12xlarge"]
      max_vcpus               = 192
      scratch_gb              = 2048
      provisioning            = "EC2"
    }
  }

  # Effective per-stage map consumed by the launch templates, compute environments, and
  # queues below. Selects the x86 or Graviton family per stage from var.use_graviton; every
  # other field is copied through unchanged. This is the single place the arch switch happens.
  index_generation_stages = {
    for name, cfg in local.index_generation_stages_base : name => {
      instance_types = var.use_graviton ? cfg.instance_types_graviton : cfg.instance_types_x86
      max_vcpus      = cfg.max_vcpus
      scratch_gb     = cfg.scratch_gb
      provisioning   = cfg.provisioning
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

# Lever 2 (platform-overhaul 548): run the index-generation per-stage Batch compute
# environments on Graviton3 (arm64) instead of Track A's x86 families. Declared here rather
# than in the env-generated variables.tf (which only carries deployment-derived values)
# because it is a static architecture toggle, co-located with its only consumer -- the same
# pattern as lambda_log_retention_in_days above.
#
# Default TRUE: Graviton3 (arm64) is now the applied/default architecture for the
# index-generation stages. It was previously held at false and enabled only via a manual
# TF_VAR_use_graviton=true at apply time, which meant any apply that forgot the override
# silently reverted the live CEs to x86 -- so the toggle is persisted here instead of relying
# on an ambient env var. Both original gates are satisfied: the multi-arch/arm64
# index-generation SWIPE image is published to ECR (swipe:v1.4.9-seqtoid.1-arm64), and the
# arm64 pipeline was validated end-to-end on m7g/r7g (per-stage provisioning + ncbi-compress +
# diamond) before this flip. When true the ECS-optimized AMI lookup also switches to the arm64
# image so the AMI arch matches the instance arch. To revert to Track A's x86 per-stage
# families (e.g. if an arm64 AUPR regression is found), flip this one line back to false.
variable "use_graviton" {
  type        = bool
  default     = true
  description = "Run index-generation Batch stages on Graviton3 (arm64). Default true; flip to false to fall back to Track A x86 per-stage families."
}

data "aws_ssm_parameter" "idseq_batch_ami" {
  # NOTE: the mock-aws/aws conditional is because moto errors on creating ssm parameters that begin with aws or ssm.
  #
  # Graviton (Lever 2): arm64 Batch hosts must boot an arm64 ECS-optimized AMI, so when
  # var.use_graviton is set the SSM lookup switches to the AWS-published arm64 image_id
  # parameter (.../amazon-linux-2/arm64/recommended/image_id) instead of the x86_64 one
  # (.../amazon-linux-2/recommended/image_id). Both the launch templates and the compute
  # environments below read this one data source, so the AMI arch tracks the instance arch.
  # Test stays on the x86 mock param: moto only seeds that path (Makefile) and the test env
  # collapses every stage to on-demand "optimal", so an arm64 AMI is neither seeded nor needed.
  name = "/${var.DEPLOYMENT_ENVIRONMENT == "test" ? "mock-aws" : "aws"}/service/ecs/optimized-ami/amazon-linux-2/${var.use_graviton && var.DEPLOYMENT_ENVIRONMENT != "test" ? "arm64/" : ""}recommended/image_id"
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

  # Make each new launch-template version the DEFAULT so the Batch compute environment (which
  # references this template by name, i.e. its default version) actually picks up changes -- e.g.
  # the download scratch bump. Without this, a config change creates a new version but the CE keeps
  # launching instances from the stale default (the 500 GB -> 2 TB download fix would not take).
  update_default_version = true

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
      DEPLOYMENT_ENVIRONMENT   = var.DEPLOYMENT_ENVIRONMENT
      INDEX_GENERATION_SFN_ARN = module.swipe.sfn_arns["index-generation"]
      # Fan-out index-generation version (semver SSOT, platform-overhaul #843). Must match the
      # published WDL prefix s3://<workflows>/index-generation-<VER>/ and the ECR tag
      # index-generation:<VER>. Bump all three together when releasing a new index-gen version.
      INDEX_GENERATION_WORKFLOW_VERSION = "v2.5.0"
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
