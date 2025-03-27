output "invocation_lambda" {
  value       = aws_lambda_function.custom_invocation.function_name
  description = "Lambda to be invoked by other idseq services for sending slack messages"
}