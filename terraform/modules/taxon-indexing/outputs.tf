output "lambda_arn" {
  value = aws_lambda_function.index_taxons.arn
}

output "lambda_name" {
  value = aws_lambda_function.index_taxons.function_name
}
