module "swipe" {
  # Vendored in-house fork (public IT-ARS mirror of thorvath-slower/swipe): pinned by
  # immutable tag. Adds the arm64 index-generation runner + seqtoid branding on top of
  # upstream v1.4.9; the module interface is a strict superset, so this is a drop-in.
  source = "github.com/IT-Academic-Research-Services/swipe?ref=v1.4.9-seqtoid.1"
  tags = {
    Name = "swipe"
  }

  app_name        = "idseq-swipe-${var.DEPLOYMENT_ENVIRONMENT}"
  job_policy_arns = [aws_iam_policy.idseq_batch_main_job.arn, "arn:aws:iam::aws:policy/AmazonEC2ContainerRegistryReadOnly"]
  call_cache      = true

  # mocking parameters
  ami_ssm_parameter = var.DEPLOYMENT_ENVIRONMENT == "test" ? "/mock-aws/service/ecs/optimized-ami/amazon-linux-2/recommended/image_id" : "/aws/service/ecs/optimized-ami/amazon-linux-2/recommended/image_id"
  aws_endpoint_url  = var.DEPLOYMENT_ENVIRONMENT == "test" ? "http://awsnet:5000" : null
  use_spot          = var.DEPLOYMENT_ENVIRONMENT != "test"

  network_info = {
    vpc_id           = aws_vpc.idseq.id
    batch_subnet_ids = [for subnet in aws_subnet.idseq : subnet.id]
  }

  spot_min_vcpus = lookup({
    "staging" : 16,
    "prod" : 16,
    # dev is often used for batches of experiments
    #   we want to scale down to 0 because startup time doesn't matter
    #   but we should also enable high concurrency so we can run these
    #   experiments quickly
    "dev" : 0,
  }, var.DEPLOYMENT_ENVIRONMENT, 0)
  spot_max_vcpus = lookup({
    "staging" : 128,
    "prod" : 4096,
    # dev is often used for batches of experiments
    #   we want to scale down to 0 because startup time doesn't matter
    #   but we should also enable high concurrency so we can run these
    #   experiments quickly
    "dev" : 4096,
  }, var.DEPLOYMENT_ENVIRONMENT, 64)

  on_demand_min_vcpus = 0
  on_demand_max_vcpus = lookup({
    "staging" : 128,
    "prod" : 4096,
    # dev is often used for batches of experiments
    #   we want to scale down to 0 because startup time doesn't matter
    #   but we should also enable high concurrency so we can run these
    #   experiments quickly
    "dev" : 4096,
  }, var.DEPLOYMENT_ENVIRONMENT, 64)

  wdl_workflow_s3_prefix   = aws_s3_bucket.workflows.bucket
  batch_ec2_instance_types = var.DEPLOYMENT_ENVIRONMENT == "test" ? ["optimal"] : ["r5d"]

  sfn_template_files = {
    "short-read-mngs" : {
      path                = "${path.module}/sfn_templates/short-read-mngs.yml",
      extra_template_vars = {},
    },
    "index-generation" : {
      path = "${path.module}/sfn_templates/index-generation.yml",
      # Multi-stage index-generation (Lever 1, Track A): each phase routes to its own
      # right-sized per-stage queue. The Index stage runs on the spot queue and falls back
      # to the on-demand queue on a spot reclaim (see sfn_templates/index-generation.yml).
      extra_template_vars = {
        "index_generation_download_job_queue_arn" : aws_batch_job_queue.index_generation["download"].arn,
        # Download split (799): per-database queues so nt/nr/taxonomy run concurrently on
        # separate right-sized boxes. Wired here so the SFN template's Parallel Download
        # branches can route to them (routing switch is 799 step 2). Additive: the single
        # `download` arn above stays until that switch removes it.
        "index_generation_download_taxonomy_job_queue_arn" : aws_batch_job_queue.index_generation["download_taxonomy"].arn,
        "index_generation_download_nt_job_queue_arn" : aws_batch_job_queue.index_generation["download_nt"].arn,
        "index_generation_download_nr_job_queue_arn" : aws_batch_job_queue.index_generation["download_nr"].arn,
        "index_generation_compress_job_queue_arn" : aws_batch_job_queue.index_generation["compress"].arn,
        "index_generation_index_spot_job_queue_arn" : aws_batch_job_queue.index_generation["index_spot"].arn,
        "index_generation_index_on_demand_job_queue_arn" : aws_batch_job_queue.index_generation["index_ondemand"].arn,
        # Graviton (Lever 2, CZID-776): override the shared amd64 swipe_main job-def with the
        # dedicated arm64 job-def for index-generation only. swipe-sfn renders the template with
        # merge({batch_job_definition_name = <swipe_main>...}, extra_template_vars), and merge's
        # second arg wins, so this replaces batch_job_definition_name for THIS SFN alone. The
        # arm64 CEs (r7g/m7g) can only exec the arm64 SWIPE runner; short-read-mngs is untouched.
        "batch_job_definition_name" : aws_batch_job_definition.index_generation_arm64.name,
      },
    },
  }
  # Per-stage container memory (MB) defaults swipe injects as <Stage>SPOTMemory /
  # <Stage>EC2Memory into the SFN input. Download/Compress/Index are the new index-generation
  # stages (Lever 1, Track A); Run stays for swipe's built-in single-stage default-wdl
  # machine; HostFilter/NonHostAlignment/Postprocess/Experimental are short-read-mngs. The
  # start_index_generation lambda can still override these per run. Index seeds from PR-1
  # per-task sizing; confirm against a profiling run before prod.
  stage_memory_defaults = {
    Download : {
      spot      = 14000
      on_demand = 14000
    },
    Compress : {
      spot      = 380000
      on_demand = 380000
    },
    Index : {
      spot      = 128000
      on_demand = 250000
    },
    Run : {
      spot      = 128000
      on_demand = 256000
    },
    HostFilter : {
      spot      = 128000
      on_demand = 256000
    },
    NonHostAlignment : {
      spot      = 128000
      on_demand = 256000
    },
    Postprocess : {
      spot      = 128000
      on_demand = 256000
    },
    Experimental : {
      spot      = 128000
      on_demand = 256000
    }
  }

  # TODO: Use the correct/renamed buckets, once they get renamed, or built per-environment
  #       czid-public-references -> seqtoid-public-references or wherever the public data lives
  #       idseq-workflows -> cypherid-samples-deleteme -> seqtoid-workflows or wherever the WDL files live
  #       idseq-database -> Is this supposed to be the same as idseq-workflows or seqtoid-public-references, or some other component?
  # Per-PR preview sandboxes upload to their OWN bucket (seqtoid-preview-samples-<env>-<acct>,
  # cypherid-web-infra), not idseq-samples-<env>. They were given a separate bucket so a sandbox can
  # never write into `seqtoid-sandbox` -- which despite the name holds ~4.8 TB of the team's research
  # data (validation sets, time trials, taxon indexes) and which the preview role could previously
  # DELETE from.
  #
  # But THIS pipeline was never told that bucket exists, so a sandbox's Step Functions execution died
  # 1.4s in at the first state:
  #   PreprocessInput -> AccessDenied: idseq-swipe-dev-preprocess_input is not authorized to perform
  #   s3:PutObject on seqtoid-preview-samples-dev-.../samples/1/1/1/short-read-mngs-8/host_filter_input.json
  # The sandbox could dispatch, but the pipeline could not read its inputs or write its outputs --
  # leaving the sandbox usable for UI review only, never for running a sample.
  #
  # This list is the ONLY feed for those grants: swipe expands it into the sfn-io-helper lambda role
  # policies (one shared document, for_each over 8 lambdas) and the batch-job policy. Same actions,
  # same bucket-wide scope idseq-samples-<env> already has -- not a broader grant, just the same one
  # for the bucket sandboxes actually use.
  #
  # DEV ONLY, deliberately. The lookup's default arm is shared by dev, staging, sandbox AND test
  # (only prod has its own), so appending unconditionally would grant this in staging and sandbox
  # too. Preview sandboxes exist only on dev; the bucket does not exist elsewhere.
  workspace_s3_prefixes = lookup(
    {
      "prod" : ["idseq-prod-samples-us-west-2", "czid-public-references", local.s3_bucket_public_references, local.s3_bucket_workflows, "idseq-prod-system-test"],
    },
    var.DEPLOYMENT_ENVIRONMENT,
    concat(
      ["idseq-samples-${var.DEPLOYMENT_ENVIRONMENT}-${var.AWS_ACCOUNT_ID}", "czid-public-references", local.s3_bucket_public_references, local.s3_bucket_workflows],
      var.DEPLOYMENT_ENVIRONMENT == "dev" ? ["seqtoid-preview-samples-dev-${var.AWS_ACCOUNT_ID}"] : []
    )
  )

  extra_env_vars = {
    DEPLOYMENT_ENVIRONMENT = var.DEPLOYMENT_ENVIRONMENT,

  }

  sqs_queues = {
    "web" : {
      dead_letter : var.DEPLOYMENT_ENVIRONMENT == "dev" ? "true" : "false",
      // We have different settings for dev below b/c multiple dev machines may view
      // and ignore the messages, which drives up the receiveCount. Timeout is lower
      // so that the intended machine may see it faster:
      visibility_timeout_seconds : var.DEPLOYMENT_ENVIRONMENT == "dev" ? "10" : "120",
    },
  }

  output_status_json_files = true
}

resource "aws_ssm_parameter" "sfn_notifications_queue_arn" {
  name  = "/idseq-${var.DEPLOYMENT_ENVIRONMENT}-web/SFN_NOTIFICATIONS_QUEUE_ARN"
  type  = "String"
  value = module.swipe.sfn_notification_queue_arns["web"]
}

data "aws_iam_policy_document" "ecs-assume-role" {
  statement {
    principals {
      type        = "Service"
      identifiers = ["ecs-tasks.amazonaws.com"]
    }

    actions = ["sts:AssumeRole"]
  }
}

resource "aws_iam_role" "aegea-ecs" {
  name               = "aegea.ecs"
  description        = "undocumented but required IAM Role needed by Workflows from the ${var.DEPLOYMENT_ENVIRONMENT} ECS Workflow Service(s)"
  assume_role_policy = data.aws_iam_policy_document.ecs-assume-role.json
}

resource "aws_iam_role_policy_attachment" "aegea-ecs-ec2-role-policy-attach" {
  role       = aws_iam_role.aegea-ecs.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonEC2ContainerServiceforEC2Role"
}

resource "aws_iam_role_policy_attachment" "aegea-ecs-batch-role-policy-attach" {
  role       = aws_iam_role.aegea-ecs.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSBatchServiceRole"
}

resource "aws_security_group" "aegea-ecs-sg" {
  name        = "aegea.ecs"
  description = "undocumented but required Security Group needed by Workflows from the ${var.DEPLOYMENT_ENVIRONMENT} ECS Workflow Service(s)"
  vpc_id      = aws_vpc.idseq.id
  tags = {
    Name = "aegea.ecs"
  }
}

# CZID-56: the aegea/SWIPE ECS workflow tier needs to reach AWS service endpoints (ECR image
# pulls, S3, Step Functions, Batch, CloudWatch Logs) over the IGW. The single all-protocol/all-port
# rule to 0.0.0.0/0 is replaced with per-port rules (HTTPS + HTTP + DNS): the destination stays
# 0.0.0.0/0 (arbitrary AWS-owned public IPs — scopable only under CZID-352 VPC endpoints), but
# arbitrary-port outbound (the C2/exfil path AWS-0104 warns about) is removed. Trivy AWS-0104 still
# flags the 0.0.0.0/0 destination on each rule — kept + baselined in .trivyignore with this
# justification. (Checkov CKV_AWS_382 does not apply to aws_vpc_security_group_egress_rule.)
resource "aws_vpc_security_group_egress_rule" "aegea-ecs-allow_https_ipv4" {
  security_group_id = aws_security_group.aegea-ecs-sg.id
  description       = "HTTPS to AWS service endpoints / ECR / S3"
  cidr_ipv4         = "0.0.0.0/0"
  ip_protocol       = "tcp"
  from_port         = 443
  to_port           = 443
}

resource "aws_vpc_security_group_egress_rule" "aegea-ecs-allow_http_ipv4" {
  security_group_id = aws_security_group.aegea-ecs-sg.id
  description       = "HTTP for package/mirror pulls"
  cidr_ipv4         = "0.0.0.0/0"
  ip_protocol       = "tcp"
  from_port         = 80
  to_port           = 80
}

resource "aws_vpc_security_group_egress_rule" "aegea-ecs-allow_dns_udp_ipv4" {
  security_group_id = aws_security_group.aegea-ecs-sg.id
  description       = "DNS (UDP)"
  cidr_ipv4         = "0.0.0.0/0"
  ip_protocol       = "udp"
  from_port         = 53
  to_port           = 53
}

resource "aws_vpc_security_group_egress_rule" "aegea-ecs-allow_dns_tcp_ipv4" {
  security_group_id = aws_security_group.aegea-ecs-sg.id
  description       = "DNS (TCP)"
  cidr_ipv4         = "0.0.0.0/0"
  ip_protocol       = "tcp"
  from_port         = 53
  to_port           = 53
}
