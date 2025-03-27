version 1.0

task RunValidateInput {
  input {
    String docker_image_id
    String aws_region
    String deployment_env
    String s3_wd_uri
    File fastqs_0
    File? fastqs_1
  }
  command<<<
  export AWS_DEFAULT_REGION=~{aws_region} DEPLOYMENT_ENVIRONMENT=~{deployment_env}
  set -x
  idseq-dag-run-step --workflow-name test \
    --step-module idseq_dag.steps.run_validate_input \
    --step-class PipelineStepRunValidateInput \
    --step-name test_out \
    --input-files '[["~{fastqs_0}", "~{fastqs_1}"]]' \
    --output-files '["validate_input_summary.json", "output_R1.fastq", "output_R2.fastq"]' \
    --output-dir-s3 '~{s3_wd_uri}' \
    --additional-files '{}' \
    --additional-attributes '{"truncate_fragments_to": 75000000, "file_ext": "fastq"}'
  >>>
  output {
    File validate_input_summary_json = "validate_input_summary.json"
    File output_R1_fastq = "output_R1.fastq"
    File output_R2_fastq = "output_R2.fastq"
    File? output_read_count = "test_out.count"
    File? input_read_count = "fastqs.count"
  }
  runtime {
    docker: docker_image_id
  }
}

workflow idseq_test {
  String docker_image_id = "docker.pkg.github.com/chanzuckerberg/czid-workflows/czid-short-read-mngs-public"
  String aws_region = "us-west-2"
  String deployment_env = "dev"
  String s3_wd_uri = "s3://idseq-main-1"
  input {
    File fastqs_0
    File? fastqs_1
  }

  call RunValidateInput {
    input:
      docker_image_id = docker_image_id,
      aws_region = aws_region,
      deployment_env = deployment_env,
      s3_wd_uri = s3_wd_uri,
      fastqs_0 = fastqs_0,
      fastqs_1 = fastqs_1
  }

  output {
    File test_out_validate_input_summary_json = RunValidateInput.validate_input_summary_json
    File test_out_output_R1_fastq = RunValidateInput.output_R1_fastq
    File test_out_output_R2_fastq = RunValidateInput.output_R2_fastq
    File? test_out_count = RunValidateInput.output_read_count
    File? input_read_count = RunValidateInput.input_read_count
  }
}
