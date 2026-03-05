
resource "aws_iam_role" "idseq_batch_service_role" {
  name = "idseq-${var.DEPLOYMENT_ENVIRONMENT}-batch-service"
  assume_role_policy = templatefile("${path.module}/iam_policy_templates/trust_policy.json", {
    trust_services = ["batch"]
    # TODO:
    # Add 030998640247:assumed-role/idseq-staging-batch-service/aws-batch
    # is not authorized to perform: logs:DescribeLogGroups
    # on resource: arn:aws:logs:us-west-2:030998640247:log-group::log-stream:
    # because no identity-based policy allows the logs:DescribeLogGroups action
    #
    # │ Error: waiting for Batch Compute Environment (idseq-staging-minimap2-EC2-1-20260206003026951500000009)
    # delete: unexpected state 'INVALID', wanted target ''. last error: CLIENT_ERROR -
    # Access Denied during delete ECS cluster
    # arn:aws:ecs:us-west-2:030998640247:cluster/idseq-staging-minimap2-EC2-1-20260206003026951500000009_Batch_00f49724-c894-3571-b87f-6a5fb996beea
    # with error User: arn:aws:sts::030998640247:assumed-role/idseq-staging-batch-service/aws-batch is not authorized to perform:
    # ecs:DeleteCluster on resource: arn:aws:ecs:us-west-2:030998640247:cluster/idseq-staging-minimap2-EC2-1-20260206003026951500000009_Batch_00f49724-c894-3571-b87f-6a5fb996beea
    # because no identity-based policy allows the ecs:DeleteCluster action
  })
  tags = local.common_tags
}

resource "aws_iam_role_policy_attachment" "idseq_batch_service_role" {
  role       = aws_iam_role.idseq_batch_service_role.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSBatchServiceRole"
}

resource "aws_iam_role_policy_attachment" "idseq_batch_service_role-logs" {
  role       = aws_iam_role.idseq_batch_service_role.name
  policy_arn = "arn:aws:iam::aws:policy/CloudWatchLogsReadOnlyAccess"
}

data "aws_iam_policy_document" "idseq_batch_service_role-destroy" {
  statement {
    effect = "Allow"
    actions = [
      "ecs:DeleteCluster",
    ]
    resources = [
      "arn:aws:ecs:us-west-2:${var.AWS_ACCOUNT_ID}:cluster/idseq-${var.DEPLOYMENT_ENVIRONMENT}-diamond-*",
      "arn:aws:ecs:us-west-2:${var.AWS_ACCOUNT_ID}:cluster/idseq-${var.DEPLOYMENT_ENVIRONMENT}-index-generation-*",
      "arn:aws:ecs:us-west-2:${var.AWS_ACCOUNT_ID}:cluster/idseq-${var.DEPLOYMENT_ENVIRONMENT}-minimap2-*",
      "arn:aws:ecs:us-west-2:${var.AWS_ACCOUNT_ID}:cluster/idseq-swipe-*",
    ]
  }
}

resource "aws_iam_policy" "idseq_batch_service_role-destroy" {
  name        = "idseq_batch_service_role-destroy"
  description = "Policy to allow deleting of ECS clusters that execute WDL pipelines"
  policy      = data.aws_iam_policy_document.idseq_batch_service_role-destroy.json
}

resource "aws_iam_role_policy_attachment" "idseq_batch_service_role-destroy" {
  role       = aws_iam_role.idseq_batch_service_role.name
  policy_arn = aws_iam_policy.idseq_batch_service_role-destroy.arn
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
