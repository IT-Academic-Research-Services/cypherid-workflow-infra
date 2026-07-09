# aws_lambda_function.custom_invocation is code-generated into this module as
# chalice.tf.json by `make package-lambdas` (see the note in main.tf).
output "invocation_lambda" {
  value       = aws_lambda_function.custom_invocation.function_name
  description = "Lambda to be invoked by other idseq services for sending slack messages"
}