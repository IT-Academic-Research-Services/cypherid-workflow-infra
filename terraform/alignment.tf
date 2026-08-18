# Pinned x86_64 ECS-optimized AMI for the diamond + minimap2 alignment Batch CEs (SMP-1745).
# Both module instances read the AWS-published "latest" ECS-optimized AMI via the module's SSM
# data source, so every AWS AMI publish force-replaces all six alignment CEs on the next apply.
# The default below is the id the live alignment CEs are CURRENTLY running (read from state), so
# config == live and pinning is a no-op convergence -- no CE replacement. Bumped deliberately via
# .github/workflows/bump-batch-ami.yml (which opens a reviewable PR). Keep the `# smp-1745-ami:x86`
# marker: the bump workflow finds and rewrites this default by it.
variable "batch_ami_id_alignment_x86" {
  type        = string
  default     = "ami-027eb2efb1c4cd48d" # smp-1745-ami:x86
  description = "Pinned x86_64 ECS-optimized AMI for the diamond + minimap2 alignment Batch CEs. Default = the id live in state; bumped via .github/workflows/bump-batch-ami.yml (SMP-1745)."
}

locals {
  min_vcpus = {
    "default" : { "SPOT" : 0, "EC2" : 0 },
    "staging" : { "SPOT" : 0, "EC2" : 0 },
    "prod" : { "SPOT" : 0, "EC2" : 0 },
  }
  max_vcpus = { // 96 * 10 = 960, 96 * 100 = 9600
    "default" : { "SPOT" : 960, "EC2" : 960 },
    # dev is often used for batches of experiments
    #   we want to scale down to 0 because startup time doesn't matter
    #   but we should also enable high concurrency so we can run these
    #   experiments quickly
    "dev" : { "SPOT" : 9600, "EC2" : 9600 },
    "staging" : { "SPOT" : 4800, "EC2" : 960 },
    "prod" : { "SPOT" : 9600, "EC2" : 9600 },
  }
}

module "diamond" {
  source = "./modules/scalable-alignment-batch"

  // Environment variables
  region                 = var.AWS_DEFAULT_REGION
  deployment_environment = var.DEPLOYMENT_ENVIRONMENT
  docker_registry        = var.DOCKER_REGISTRY
  owner                  = var.OWNER
  max_vcpus              = local.max_vcpus
  min_vcpus              = local.min_vcpus

  // Network Variables
  security_group_id = aws_security_group.idseq.id
  subnet_ids        = [for subnet in aws_subnet.idseq : subnet.id]

  // Role Variables
  job_iam_role        = aws_iam_role.idseq_batch_main_job.arn
  service_iam_role    = aws_iam_role.idseq_batch_service_role.arn
  spot_fleet_iam_role = aws_iam_role.idseq_batch_spot_fleet_service_role.arn

  // Priorty Variables
  priorities = [{
    "name" : "normal",
    "priority" : 10,
  }]

  // Alignment Variables
  alignment_algorithm = "diamond"

  // Compute Variables
  // SMP-1745: pin the ECS-optimized AMI in real envs (test passes null -> module SSM fallback).
  image_id = var.DEPLOYMENT_ENVIRONMENT == "test" ? null : var.batch_ami_id_alignment_x86

  // Utility Variables

  // Still experimental, enable in dev only
  disabled = var.DEPLOYMENT_ENVIRONMENT == "test"
}

module "minimap2" {
  source = "./modules/scalable-alignment-batch"

  // Environment variables
  region                 = var.AWS_DEFAULT_REGION
  deployment_environment = var.DEPLOYMENT_ENVIRONMENT
  docker_registry        = var.DOCKER_REGISTRY
  owner                  = var.OWNER
  max_vcpus              = local.max_vcpus
  min_vcpus              = local.min_vcpus

  // Network Variables
  security_group_id = aws_security_group.idseq.id
  subnet_ids        = [for subnet in aws_subnet.idseq : subnet.id]

  // Role Variables
  job_iam_role        = aws_iam_role.idseq_batch_main_job.arn
  service_iam_role    = aws_iam_role.idseq_batch_service_role.arn
  spot_fleet_iam_role = aws_iam_role.idseq_batch_spot_fleet_service_role.arn

  // Priorty Variables
  priorities = [{
    "name" : "normal",
    "priority" : 10,
  }]

  // Alignment Variables
  alignment_algorithm = "minimap2"

  // Compute Variables
  // SMP-1745: pin the ECS-optimized AMI in real envs (test passes null -> module SSM fallback).
  image_id = var.DEPLOYMENT_ENVIRONMENT == "test" ? null : var.batch_ami_id_alignment_x86

  // Utility Variables

  // Still experimental, enable in dev only
  disabled = var.DEPLOYMENT_ENVIRONMENT == "test"
}
