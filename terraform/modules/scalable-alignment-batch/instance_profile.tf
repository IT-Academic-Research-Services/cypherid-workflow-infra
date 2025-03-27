resource "aws_iam_role" "idseq_batch_alignment_instance_role" {
  name = "idseq-${var.deployment_environment}-batch-${var.alignment_algorithm}-instance"
  assume_role_policy = templatefile("${path.module}/../../iam_policy_templates/trust_policy.json", {
    trust_services = ["ec2"]
  })
  tags = local.common_tags
}

resource "aws_iam_role_policy_attachment" "idseq_batch_alignment_instance_role_put_metric" {
  role       = aws_iam_role.idseq_batch_alignment_instance_role.name
  policy_arn = "arn:aws:iam::aws:policy/CloudWatchAgentServerPolicy"
}

resource "aws_iam_role_policy_attachment" "idseq_batch_alignment_instance_role_ecs" {
  role       = aws_iam_role.idseq_batch_alignment_instance_role.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonEC2ContainerServiceforEC2Role"
}

resource "aws_iam_role_policy_attachment" "idseq_batch_alignment_instance_role_ssm" {
  role       = aws_iam_role.idseq_batch_alignment_instance_role.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

resource "aws_iam_policy" "database_bucket_read" {
  name   = "idseq-${var.deployment_environment}-batch-${var.alignment_algorithm}-database-bucket-read"
  policy = file("${path.module}/../../iam_policy_templates/database_bucket_read_policy.json")
}

resource "aws_iam_role_policy_attachment" "idseq_batch_extra_instance_permissions_fixme" {
  role       = aws_iam_role.idseq_batch_alignment_instance_role.name
  policy_arn = aws_iam_policy.database_bucket_read.arn
}

resource "aws_iam_instance_profile" "idseq_batch_alignment" {
  name = "idseq-${var.deployment_environment}-batch-${var.alignment_algorithm}"
  role = aws_iam_role.idseq_batch_alignment_instance_role.name
}
