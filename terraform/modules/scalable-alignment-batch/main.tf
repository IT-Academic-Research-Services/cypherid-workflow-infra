locals {
  service_name        = "idseq-${var.deployment_environment}-${var.alignment_algorithm}"
  provisioning_models = ["EC2", "SPOT"]
  common_tags = {
    managedBy = "terraform"
    project   = "idseq"
    env       = var.deployment_environment
    service   = local.service_name
    owner     = var.owner
  }
}

data "aws_ssm_parameter" "idseq_batch_ami" {
  # NOTE: this conditional is because moto errors on creating ssm parameters that begin with aws or ssm
  name = "/${var.deployment_environment == "test" ? "mock-aws" : "aws"}/service/ecs/optimized-ami/amazon-linux-2/recommended/image_id"
}

locals {
  user_data_spot = base64encode(templatefile("${path.module}/container_instance_user_data_spot.tpl", {
    log_configuration = templatefile("${path.module}/log-config.json.tpl", {
      namespace = local.service_name
      region    = var.region
    })
  }))
  user_data_ec2 = base64encode(templatefile("${path.module}/container_instance_user_data_ec2.tpl", {
    log_configuration = templatefile("${path.module}/log-config.json.tpl", {
      namespace = local.service_name
      region    = var.region
    })
  }))
}

resource "aws_launch_template" "alignment_launch_template_ec2" {
  # AWS Batch pins a specific version of the launch template when a compute environment is created.
  # The CE does not support updating this version, and needs replacing (redeploying) if launch template contents change.
  # The launch template resource increments its version when contents change, but the compute environment resource does
  # not recognize this change. We bind the launch template name to user data contents here, so any changes to user data
  # will cause the whole launch template to be replaced, forcing the compute environment to pick up the changes.
  name = "${local.service_name}-batch-${md5(local.user_data_ec2)}"

  user_data = local.user_data_ec2
  tags      = local.common_tags

  # NOTE[JH]: This setting makes IMDSv2 required. Any software that needs to talk to the metadata service
  # needs to do so using the v2 endpoint.
  # https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/configuring-instance-metadata-service.html
  metadata_options {
    http_endpoint               = "enabled"
    http_tokens                 = "required"
    http_put_response_hop_limit = 2
  }
  # EC2 requires more disk space than the spot (if a job fails on spot we want to retry with more disk)
  dynamic "block_device_mappings" {
    for_each = toset(["f", "g"])

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

resource "aws_launch_template" "alignment_launch_template_spot" {
  # AWS Batch pins a specific version of the launch template when a compute environment is created.
  # The CE does not support updating this version, and needs replacing (redeploying) if launch template contents change.
  # The launch template resource increments its version when contents change, but the compute environment resource does
  # not recognize this change. We bind the launch template name to user data contents here, so any changes to user data
  # will cause the whole launch template to be replaced, forcing the compute environment to pick up the changes.
  name = "${local.service_name}-batch-${md5(local.user_data_spot)}"

  user_data = local.user_data_spot
  tags      = local.common_tags

  # NOTE[JH]: This setting makes IMDSv2 required. Any software that needs to talk to the metadata service
  # needs to do so using the v2 endpoint.
  # https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/configuring-instance-metadata-service.html
  metadata_options {
    http_endpoint               = "enabled"
    http_tokens                 = "required"
    http_put_response_hop_limit = 2
  }
}

locals {
  compute_environment_types = {
    "SPOT-1" : {
      "provisioning_model" : "SPOT",
      "instance_type" : ["r5d.12xlarge", "r5d.16xlarge", "r5d.24xlarge", "r5dn.12xlarge", "r5dn.16xlarge", "r5dn.24xlarge"],
    },
    "SPOT-2" : {
      "provisioning_model" : "SPOT",
      "instance_type" : ["m5d.12xlarge", "m5d.16xlarge", "m5d.24xlarge"],
    },
    "EC2-1" : {
      "provisioning_model" : "EC2",
      "instance_type" : ["r5d.12xlarge", "r5d.16xlarge", "r5d.24xlarge", "r5dn.12xlarge", "r5dn.16xlarge", "r5dn.24xlarge"],
    },
  }
}

resource "aws_batch_compute_environment" "alignment_compute_environment" {
  for_each                        = var.disabled ? {} : local.compute_environment_types
  compute_environment_name_prefix = "${local.service_name}-${each.key}-"

  compute_resources {
    instance_role = aws_iam_instance_profile.idseq_batch_alignment.arn

    instance_type = each.value["instance_type"]

    tags = merge(local.common_tags, {
      Name = "${local.service_name}-${each.key}-batch"
    })

    image_id     = data.aws_ssm_parameter.idseq_batch_ami.value
    ec2_key_pair = "idseq-${var.deployment_environment}"
    # TODO: set up per-environment vcpu limits
    min_vcpus          = lookup(var.min_vcpus, var.deployment_environment, var.min_vcpus["default"])[each.value["provisioning_model"]]
    desired_vcpus      = 0
    max_vcpus          = lookup(var.max_vcpus, var.deployment_environment, var.max_vcpus["default"])[each.value["provisioning_model"]]
    security_group_ids = [var.security_group_id]

    subnets = var.subnet_ids

    type                = each.value["provisioning_model"]
    allocation_strategy = each.value["provisioning_model"] == "SPOT" ? "SPOT_CAPACITY_OPTIMIZED" : "BEST_FIT"
    bid_percentage      = 100
    spot_iam_fleet_role = var.spot_fleet_iam_role

    launch_template {
      launch_template_name = each.key == "EC2-1" ? aws_launch_template.alignment_launch_template_ec2.name : aws_launch_template.alignment_launch_template_spot.name
    }
  }

  service_role = var.service_iam_role
  type         = "MANAGED"

  lifecycle {
    create_before_destroy = true
    ignore_changes = [
      compute_resources[0].desired_vcpus,
    ]
  }
}

locals {
  compute_priority_combos = flatten([
    for provisioning_model in local.provisioning_models : [
      for priority in var.priorities : {
        "provisioning_model" : provisioning_model,
        "priority" : priority["priority"],
        "priority_name" : priority["name"],
      }
    ]
  ])
}

resource "aws_batch_job_queue" "alignment_job_queue" {
  for_each = { for combo in(var.disabled ? [] : local.compute_priority_combos) :
    "P${combo.priority}_${combo.provisioning_model}" => combo
  }
  name     = "${local.service_name}-${each.value["provisioning_model"]}-${each.value["priority_name"]}"
  state    = "ENABLED"
  priority = each.value["priority"]
  compute_environments = [for key, compute_environment in aws_batch_compute_environment.alignment_compute_environment :
    compute_environment.arn if startswith(key, each.value["provisioning_model"])
  ]
}
