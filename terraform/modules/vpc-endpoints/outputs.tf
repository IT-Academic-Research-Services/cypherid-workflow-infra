// CZID-352 — VPC endpoints module outputs.

output "s3_gateway_endpoint_id" {
  description = "ID of the S3 gateway VPC endpoint."
  value       = aws_vpc_endpoint.s3.id
}

output "s3_gateway_endpoint_prefix_list_id" {
  description = "Managed prefix-list ID of the S3 gateway endpoint. Usable to scope Batch/ECS SG egress to S3 once CZID-56 tightens the 0.0.0.0/0 rule."
  value       = aws_vpc_endpoint.s3.prefix_list_id
}

output "interface_endpoint_ids" {
  description = "Map of interface-endpoint service name -> VPC endpoint ID."
  value       = { for k, ep in aws_vpc_endpoint.interface : k => ep.id }
}

output "endpoints_security_group_id" {
  description = "ID of the security group fronting the interface endpoints (allows 443 from the VPC CIDR)."
  value       = aws_security_group.endpoints.id
}
