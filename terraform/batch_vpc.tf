data "aws_availability_zones" "available" {
  state = "available"
}

resource "aws_vpc" "idseq" {
  cidr_block           = "10.20.0.0/16"
  enable_dns_hostnames = true
  tags = {
    Name = "idseq-${var.DEPLOYMENT_ENVIRONMENT}"
  }
}

resource "aws_internet_gateway" "idseq" {
  vpc_id = aws_vpc.idseq.id
  tags = {
    Name = "idseq-${var.DEPLOYMENT_ENVIRONMENT}"
  }
}

resource "aws_route" "idseq" {
  route_table_id         = aws_vpc.idseq.default_route_table_id
  destination_cidr_block = "0.0.0.0/0"
  gateway_id             = aws_internet_gateway.idseq.id
}

resource "aws_subnet" "idseq" {
  for_each                = toset(data.aws_availability_zones.available.names)
  vpc_id                  = aws_vpc.idseq.id
  availability_zone       = each.key
  cidr_block              = cidrsubnet(aws_vpc.idseq.cidr_block, 8, index(data.aws_availability_zones.available.names, each.key))
  map_public_ip_on_launch = true
  tags = {
    Name = "idseq-${var.DEPLOYMENT_ENVIRONMENT}"
  }
}

resource "aws_security_group" "idseq" {
  # checkov:skip=CKV_AWS_382:Accepted-with-justification (register #56). This Batch tier runs in
  # public subnets with NO VPC endpoints, so it must reach AWS regional service endpoints (S3, ECR,
  # CloudWatch Logs, SSM, STS) over the IGW; narrowing egress below 0.0.0.0/0 today would break
  # image pulls / log delivery / S3 I/O on apply. The egress is made genuinely scopable by the VPC
  # endpoints architecture (CZID-352, design: VPC-ENDPOINTS-ARCHITECTURE-2026-06-29.md), after which
  # this rule is replaced with VPC-CIDR + gateway prefix-lists + explicit external rules.
  name   = "idseq-${var.DEPLOYMENT_ENVIRONMENT}"
  vpc_id = aws_vpc.idseq.id
  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}
