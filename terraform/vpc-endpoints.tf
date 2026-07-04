// CZID-352 — instantiate the VPC endpoints module for the workflow (idseq) VPC.
// Design: VPC-ENDPOINTS-ARCHITECTURE-2026-06-29.md.
//
// count guard matches the repo pattern (batch_job.tf, index-generation.tf): the `test` stage has
// no real VPC (localstack/moto mock), so the module produces zero resources there and stays empty.
// For every real env (dev/staging/prod/sandbox) this single instantiation is the SSOT — the env is
// selected by var.DEPLOYMENT_ENVIRONMENT, so all four envs are mirrored by one file.
//
// Additive + in-place-safe: adding endpoints and the S3 gateway route-table association does not
// replace the existing VPC, subnets, or the idseq/index_generation SGs.
module "vpc-endpoints" {
  count  = var.DEPLOYMENT_ENVIRONMENT == "test" ? 0 : 1
  source = "./modules/vpc-endpoints"

  deployment_environment = var.DEPLOYMENT_ENVIRONMENT

  vpc_id         = aws_vpc.idseq.id
  vpc_cidr_block = aws_vpc.idseq.cidr_block

  # Interface-endpoint ENIs land in the workflow subnets (one per AZ).
  subnet_ids = [for subnet in aws_subnet.idseq : subnet.id]

  # This VPC uses the default route table for all subnets; associate the S3 gateway endpoint with it.
  route_table_ids = [aws_vpc.idseq.default_route_table_id]
}
