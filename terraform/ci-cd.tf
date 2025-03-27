resource "aws_iam_role" "idseq_ci_cd_role" {
  name = "idseq-${var.DEPLOYMENT_ENVIRONMENT}-ci-cd"
  assume_role_policy = templatefile("${path.module}/iam_policy_templates/trust_policy.json", {
    trust_services = ["ec2"]
  })
  tags = local.common_tags
}

resource "aws_iam_role_policy_attachment" "idseq_ci_cd_ssm" {
  role       = aws_iam_role.idseq_ci_cd_role.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

resource "aws_iam_role_policy_attachment" "idseq_ci_cd_iam" {
  role       = aws_iam_role.idseq_ci_cd_role.name
  policy_arn = "arn:aws:iam::aws:policy/IAMReadOnlyAccess"
}

resource "aws_iam_role_policy_attachment" "idseq_ci_cd_ecr" {
  role       = aws_iam_role.idseq_ci_cd_role.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonEC2ContainerRegistryPowerUser"
}

resource "aws_iam_role_policy_attachment" "idseq_ci_cd_ec2" {
  role       = aws_iam_role.idseq_ci_cd_role.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonEC2ReadOnlyAccess"
}

resource "aws_iam_role_policy_attachment" "idseq_ci_cd_lambda" {
  role       = aws_iam_role.idseq_ci_cd_role.name
  policy_arn = "arn:aws:iam::aws:policy/AWSLambda_ReadOnlyAccess"
}

resource "aws_iam_role_policy_attachment" "idseq_ci_cd_cloudwatch" {
  role       = aws_iam_role.idseq_ci_cd_role.name
  policy_arn = "arn:aws:iam::aws:policy/CloudWatchFullAccess"
}

resource "aws_iam_instance_profile" "idseq_ci_cd" {
  name = aws_iam_role.idseq_ci_cd_role.name
  role = aws_iam_role.idseq_ci_cd_role.name
}

resource "aws_iam_policy" "idseq_ci_cd" {
  name = "idseq-${var.DEPLOYMENT_ENVIRONMENT}-ci-cd"
  # contains minimal permissions for running packer: https://www.packer.io/docs/builders/amazon#iam-task-or-instance-role
  #   these may be overly broad
  policy = templatefile("${path.module}/iam_policy_templates/ci_cd.json", {
    AWS_DEFAULT_REGION     = var.AWS_DEFAULT_REGION,
    AWS_ACCOUNT_ID         = var.AWS_ACCOUNT_ID,
    DEPLOYMENT_ENVIRONMENT = var.DEPLOYMENT_ENVIRONMENT,
  })
}

resource "aws_iam_role_policy_attachment" "idseq_ci_cd" {
  role       = aws_iam_role.idseq_ci_cd_role.name
  policy_arn = aws_iam_policy.idseq_ci_cd.arn
}

data "aws_ami" "ubuntu_lts" {
  count       = var.DEPLOYMENT_ENVIRONMENT == "test" ? 0 : 1
  most_recent = true
  owners      = ["099720109477"]
  filter {
    name   = "name"
    values = ["ubuntu/images/hvm-ssd/ubuntu-focal-20.04-amd64-server-*"]
  }
}

resource "aws_launch_template" "idseq_ci_cd" {
  name_prefix            = "idseq-${var.DEPLOYMENT_ENVIRONMENT}-ci-cd"
  instance_type          = "t3a.xlarge"
  image_id               = var.DEPLOYMENT_ENVIRONMENT == "test" ? null : data.aws_ami.ubuntu_lts[0].id
  update_default_version = true
  user_data = base64encode(templatefile("${path.module}/ci_cd_github_actions_self_hosted_runner_user_data", {
    DEPLOYMENT_ENVIRONMENT = var.DEPLOYMENT_ENVIRONMENT
    ACTIONS_RUNNER_VERSION = "2.277.1"
  }))
  tags     = local.common_tags
  key_name = "idseq-${var.DEPLOYMENT_ENVIRONMENT}"
  iam_instance_profile {
    name = aws_iam_instance_profile.idseq_ci_cd.name
  }
  block_device_mappings {
    device_name = "/dev/sda1"
    ebs {
      volume_size = 128
      encrypted   = true
    }
  }
  tag_specifications {
    resource_type = "instance"
    tags = merge(local.common_tags, {
      Name        = "idseq-${var.DEPLOYMENT_ENVIRONMENT}-ci-cd-YOUR_GITHUB_REPO",
      github-repo = "YOUR_GITHUB_REPO",
    })
  }
  tag_specifications {
    resource_type = "volume"
    tags = merge(local.common_tags, {
      Name = "idseq-${var.DEPLOYMENT_ENVIRONMENT}-ci-cd"
    })
  }
}
