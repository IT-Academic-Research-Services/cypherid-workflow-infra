
resource "aws_iam_role" "idseq_batch_service_role" {
  name = "idseq-${var.DEPLOYMENT_ENVIRONMENT}-batch-service"
  assume_role_policy = templatefile("${path.module}/iam_policy_templates/trust_policy.json", {
    trust_services = ["batch"]
  })
  tags = local.common_tags
}

resource "aws_iam_role_policy_attachment" "idseq_batch_service_role" {
  role       = aws_iam_role.idseq_batch_service_role.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSBatchServiceRole"
}

resource "aws_iam_role" "idseq_batch_spot_fleet_service_role" {
  name = "idseq-${var.DEPLOYMENT_ENVIRONMENT}-batch-spot-fleet-service"
  assume_role_policy = templatefile("${path.module}/iam_policy_templates/trust_policy.json", {
    trust_services = ["spotfleet"]
  })
  tags = local.common_tags
}

resource "aws_iam_role_policy_attachment" "idseq_batch_spot_fleet_service_role" {
  role       = aws_iam_role.idseq_batch_spot_fleet_service_role.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonEC2SpotFleetTaggingRole"
}

resource "aws_iam_role" "idseq_batch_main_instance_role" {
  name = "idseq-${var.DEPLOYMENT_ENVIRONMENT}-batch-main-instance"
  assume_role_policy = templatefile("${path.module}/iam_policy_templates/trust_policy.json", {
    trust_services = ["ec2"]
  })
  tags = local.common_tags
}

resource "aws_iam_role_policy_attachment" "idseq_batch_main_instance_role_put_metric" {
  role       = aws_iam_role.idseq_batch_main_instance_role.name
  policy_arn = "arn:aws:iam::aws:policy/CloudWatchAgentServerPolicy"
}

resource "aws_iam_role_policy_attachment" "idseq_batch_main_instance_role_ecs" {
  role       = aws_iam_role.idseq_batch_main_instance_role.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonEC2ContainerServiceforEC2Role"
}

resource "aws_iam_role_policy_attachment" "idseq_batch_main_instance_role_ssm" {
  role       = aws_iam_role.idseq_batch_main_instance_role.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

resource "aws_iam_instance_profile" "idseq_batch_main" {
  name = "idseq-${var.DEPLOYMENT_ENVIRONMENT}-batch-main"
  role = aws_iam_role.idseq_batch_main_instance_role.name
}