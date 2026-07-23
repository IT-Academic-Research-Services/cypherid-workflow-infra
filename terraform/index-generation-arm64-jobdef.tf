# Dedicated arm64 (Graviton) Batch job definition for the multi-stage index-generation stages
# (Lever 2, CZID-776).
#
# The shared swipe main job-def (idseq-swipe-dev-main) runs the amd64 SWIPE runner image
# (ghcr.io/chanzuckerberg/swipe:v1.4.9). AWS Batch launches THAT orchestrator image (not our
# per-task index-generation image), and it is amd64-only, so on the arm64/Graviton
# index-generation compute environments it dies with `exec /usr/local/bin/init.sh: exec format
# error`. This job-def is a clone of the deployed swipe_main container properties with the
# image -- and MINIWDL__S3PARCP__DOCKER_IMAGE (s3parcp runs the same swipe image) -- swapped to
# the arm64 SWIPE runner published to dev ECR from the thorvath-slower/swipe fork
# (swipe:v1.4.9-seqtoid.1-arm64, TARGETARCH-parameterized; base/miniwdl unchanged).
#
# ONLY the index-generation SFN is pointed at this job-def (via swipe.tf extra_template_vars);
# short-read-mngs keeps the shared amd64 swipe_main job-def untouched, so nothing on x86
# changes.
#
# NOTE: container_properties is a captured snapshot of idseq-swipe-dev-main (rev 7) with the two
# image fields swapped -- it reuses the existing idseq-swipe-dev-batch-job role (baked in the
# JSON) and all 23 env vars / mounts / ulimits verbatim. If the swipe main job-def config
# changes, regenerate the JSON. Long-term this dedicated job-def is retired in favour of a
# multi-arch swipe image + module support (CZID-777).

resource "aws_batch_job_definition" "index_generation_arm64" {
  name = "idseq-swipe-${var.DEPLOYMENT_ENVIRONMENT}-index-generation-arm64"
  type = "container"
  tags = { Name = "swipe" }

  retry_strategy {
    # Matches swipe_main: retries are configured in the SFN, not the job.
    attempts = 1
  }

  timeout {
    attempt_duration_seconds = 86400
  }

  container_properties = file("${path.module}/index_generation_arm64_container_properties.json")

  lifecycle {
    create_before_destroy = true
  }
}
