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
  # CZID-56: this Batch tier runs in public subnets with NO VPC endpoints, so it must reach AWS
  # regional service endpoints (S3, ECR, CloudWatch Logs, SSM, STS) over the IGW. The *destination*
  # stays 0.0.0.0/0 for now (those endpoints are arbitrary AWS-owned public IPs); it becomes genuinely
  # CIDR/prefix-list-scopable only under the VPC endpoints architecture (CZID-352, design:
  # VPC-ENDPOINTS-ARCHITECTURE-2026-06-29.md), after which this is replaced with VPC-CIDR + gateway
  # prefix-lists + explicit external rules.
  # What we CAN tighten now: egress is narrowed off all-protocol/all-port ("-1") to the exact
  # ports these workloads use — HTTPS (AWS APIs, ECR, S3), HTTP (package/mirror pulls) and DNS.
  # This removes arbitrary-port outbound (the C2/exfil path the finding warns about) and clears
  # CKV_AWS_382. Trivy AWS-0104 still flags the 0.0.0.0/0 destination — kept, baselined in
  # .trivyignore with this justification, until CZID-352 lands.
  name   = "idseq-${var.DEPLOYMENT_ENVIRONMENT}"
  vpc_id = aws_vpc.idseq.id
  egress {
    description = "HTTPS to AWS service endpoints / ECR / S3"
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }
  egress {
    description = "HTTP for package/mirror pulls"
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
