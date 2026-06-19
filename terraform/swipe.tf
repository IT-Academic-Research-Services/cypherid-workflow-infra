module "swipe" {
  # TODO: Use chanzuckerberg/swipe once they merge in PR https://github.com/chanzuckerberg/swipe/pull/124
  #       But don't hold your breath. That repo hasn't been updated since April 2025
  # source = "github.com/chanzuckerberg/swipe?ref=v1.4.9"
  source = "github.com/jsims-slower/swipe"
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
      extra_template_vars = {
        "index_generation_job_queue_arn" : aws_batch_job_queue.index_generation_job_queue.arn,
      },
    },
  }
  stage_memory_defaults = {
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
  workspace_s3_prefixes = lookup(
    {
      "prod" : ["idseq-prod-samples-us-west-2", "czid-public-references", local.s3_bucket_public_references, local.s3_bucket_workflows, "idseq-prod-system-test"],
    },
    var.DEPLOYMENT_ENVIRONMENT,
    ["idseq-samples-${var.DEPLOYMENT_ENVIRONMENT}-${var.AWS_ACCOUNT_ID}", "czid-public-references", local.s3_bucket_public_references, local.s3_bucket_workflows]
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
    "nextgen-web" : {
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

resource "aws_vpc_security_group_egress_rule" "aegea-ecs-allow_all_traffic_ipv4" {
  security_group_id = aws_security_group.aegea-ecs-sg.id
  cidr_ipv4         = "0.0.0.0/0"
  ip_protocol       = "-1" # semantically equivalent to all ports
}
