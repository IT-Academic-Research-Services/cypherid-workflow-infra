version 1.0

task RunCZIDDedup {
  input {
    String docker_image_id
    String aws_region
    String deployment_env
    String s3_wd_uri
    File test_in_input_R1_fa
  }
  command<<<
  export AWS_DEFAULT_REGION=~{aws_region} DEPLOYMENT_ENVIRONMENT=~{deployment_env}
  set -x
  idseq-dag-run-step --workflow-name test \
    --step-module idseq_dag.steps.run_czid_dedup \
    --step-class PipelineStepRunCZIDDedup \
    --step-name test_out \
    --input-files '[["~{test_in_input_R1_fa}"]]' \
    --output-files '["output_R1.fa", "clusters.csv", "duplicate_cluster_sizes.tsv"]' \
    --output-dir-s3 '~{s3_wd_uri}' \
    --additional-files '{}' \
    --additional-attributes '{}'
  >>>
  output {
    File output_R1_fa = "output_R1.fa"
    File clusters_csv = "clusters.csv"
    File duplicate_cluster_sizes_tsv = "duplicate_cluster_sizes.tsv"
    File? output_read_count = "test_out.count"
  }
  runtime {
    docker: docker_image_id
  }
}

workflow czid_test {
  String docker_image_id = "docker.pkg.github.com/chanzuckerberg/czid-workflows/czid-short-read-mngs-public"
  String aws_region = "us-west-2"
  String deployment_env = "dev"
  String s3_wd_uri = "s3://czid-main-1"
  input {
    File test_in_input_R1_fa
  }

  call RunCZIDDedup {
    input:
      docker_image_id = docker_image_id,
      aws_region = aws_region,
      deployment_env = deployment_env,
      s3_wd_uri = s3_wd_uri,
      test_in_input_R1_fa = test_in_input_R1_fa
  }

  output {
    File test_out_output_R1_fa = RunCZIDDedup.output_R1_fa
    File test_out_clusters_csv = RunCZIDDedup.clusters_csv
    File test_out_duplicate_cluster_sizes_tsv = RunCZIDDedup.duplicate_cluster_sizes_tsv
    File? test_out_count = RunCZIDDedup.output_read_count
  }
}
