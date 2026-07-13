// CZID-352 — VPC endpoints for the Batch/workflow compute tier.
// Design: VPC-ENDPOINTS-ARCHITECTURE-2026-06-29.md. This module keeps AWS-service traffic
// (S3, ECR, CloudWatch Logs, SSM, STS, Secrets Manager) on the AWS backbone instead of routing
// it out through the IGW/NAT and the public internet.

variable "deployment_environment" {
  type        = string
  description = "Deployment environment: (test, dev, staging, prod, sandbox). The caller guards instantiation with count so this module never runs for the endpoint-less test stage."
}

variable "vpc_id" {
  type        = string
  description = "ID of the workflow VPC (aws_vpc.idseq) the endpoints attach to."
}

variable "vpc_cidr_block" {
  type        = string
  description = "CIDR block of the workflow VPC. The interface-endpoint security group allows 443 from this range so in-VPC clients (Batch compute, pipeline Lambdas) can reach the endpoint ENIs."
}

variable "subnet_ids" {
  type        = list(string)
  description = "Private/compute subnet IDs (one per AZ) in which to place the interface-endpoint ENIs."
}

variable "route_table_ids" {
  type        = list(string)
  description = "Route table IDs to associate the gateway (S3) endpoint with. For this VPC that is the single default route table."
}

variable "interface_endpoint_services" {
  type        = list(string)
  description = "Short service names (the segment after com.amazonaws.<region>.) to create interface endpoints for."
  default = [
    "ecr.api",        // ECR image auth/metadata
    "ecr.dkr",        // ECR docker registry (layer pulls; layer blobs still transit the S3 gateway endpoint)
    "logs",           // CloudWatch Logs delivery
    "ssm",            // SSM parameter reads (batch jobs read /idseq-<env>-web/* params)
    "ssmmessages",    // SSM Session Manager channel (instances run amazon-ssm-agent + AmazonSSMManagedInstanceCore)
    "ec2messages",    // SSM agent <-> EC2 messages control plane
    "sts",            // regional STS role assumption
    "secretsmanager", // cloudwatch-alerting lambda + CI runner read secrets via Secrets Manager
  ]
}

variable "tags" {
  type        = map(string)
  description = "Additional tags to apply to created resources."
  default     = {}
}
