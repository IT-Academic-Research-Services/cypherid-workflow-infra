import json
import os
from uuid import uuid4

import boto3

# Multi-stage index-generation (Lever 1, Track A). The SFN state machine
# (sfn_templates/index-generation.yml) now runs three right-sized phase stages -- Download,
# Compress, Index -- instead of one monolithic RunEC2 job. This lambda builds the per-stage
# SFN input: a per-stage WDL URI, a per-stage Input payload, and the per-stage container
# memory overrides the template consumes ($.DownloadEC2Memory, $.CompressEC2Memory,
# $.IndexSPOTMemory, $.IndexEC2Memory).
#
# PER-STAGE Input CONTRACT (reconciled with the seqtoid-workflows WDL split,
# workflows/index-generation/index-generation-STAGE-SPLIT.md). A SWIPE stage runs a WHOLE
# sub-WDL locally (download.wdl / compress.wdl / index.wdl), and miniwdl rejects any
# top-level input the sub-WDL does not declare. So each stage's Input.<Stage> below carries
# ONLY the keys that stage's sub-WDL declares:
#
#   Download (index_generation_download): docker_image_id
#   Compress (index_generation_compress): docker_image_id
#   Index    (index_generation_index):    docker_image_id, index_name, previous_lineages?
#
# The cross-stage database hand-off inputs -- Compress's seven download_out_* and Index's
# seven compress_out_* (nt, nr, the four accession2taxid_*, taxdump) -- are NOT set here:
# their S3 URIs do not exist until the prior stage runs. The swipe sfn-io-helper
# (lambdas/sfn-io-helper/chalicelib/stage_io.py, index_generation_io_map) injects each
# <prev>_out_<name> into the next stage's input.json from the prior stage's identically
# named output after that stage completes (the same mechanism short-read-mngs uses for its
# <stage>_out_<name> hand-off). write_to_db / env / s3_dir are NOT sent: no sub-WDL declares
# them and miniwdl would fail on the undeclared inputs.

# Sub-WDL filenames per stage, resolved under the versioned workflows prefix. Kept here as
# the single place to reconcile with the seqtoid-workflows WDL split.
STAGE_WDL_FILENAMES = {
    "Download": "download.wdl",
    "Compress": "compress.wdl",
    "Index": "index.wdl",
}


def start_index_generation(event, *args):
    deployment_environment = os.environ["DEPLOYMENT_ENVIRONMENT"]
    state_machine_arn = os.environ["INDEX_GENERATION_SFN_ARN"]
    version = os.environ["INDEX_GENERATION_WORKFLOW_VERSION"]
    aws_region = os.environ["AWS_REGION"]
    aws_account_id = os.environ["AWS_ACCOUNT_ID"]
    bucket = os.environ["BUCKET"]
    workflows_bucket = os.environ["S3_WORKFLOWS_BUCKET"]

    # Per-stage container memory (MB). These override the swipe stage_memory_defaults for
    # this run; the SFN template reads them as $.<Stage>EC2Memory / $.IndexSPOTMemory.
    download_memory = int(os.environ["DOWNLOAD_MEMORY"])
    compress_memory = int(os.environ["COMPRESS_MEMORY"])
    index_spot_memory = int(os.environ["INDEX_SPOT_MEMORY"])
    index_ec2_memory = int(os.environ["INDEX_EC2_MEMORY"])

    sfn = boto3.client("stepfunctions")
    s3 = boto3.client("s3")

    pages = s3.get_paginator("list_objects_v2").paginate(
        Bucket=bucket,
        Prefix=f"ncbi-indexes-{deployment_environment}/",
    )

    previous_lineages = None
    for page in pages:
        for object in page["Contents"]:
            key = object["Key"]
            if key.endswith("versioned-taxid-lineages.csv.gz") and (
                not previous_lineages or key > previous_lineages
            ):
                previous_lineages = key

    index_name = event["time"][:10]

    def wdl_uri(stage):
        return f"s3://{workflows_bucket}/index-generation-{version}/{STAGE_WDL_FILENAMES[stage]}"

    docker_image_id = (
        f"{aws_account_id}.dkr.ecr.{aws_region}.amazonaws.com/index-generation:{version}"
    )

    # Per-stage Input payloads. Each stage gets ONLY the top-level inputs its sub-WDL
    # declares (see the PER-STAGE Input CONTRACT note above); the cross-stage download_out_* /
    # compress_out_* database hand-off is injected at runtime by the swipe sfn-io-helper.
    download_input = {"docker_image_id": docker_image_id}
    compress_input = {"docker_image_id": docker_image_id}
    index_input = {
        "docker_image_id": docker_image_id,
        "index_name": index_name,
    }
    # index.wdl declares `File? previous_lineages` (optional). Only pass it when a prior
    # index exists; otherwise leave it unset so the incremental-lineage step is skipped
    # instead of pointing at a non-existent object.
    if previous_lineages:
        index_input["previous_lineages"] = f"s3://{bucket}/{previous_lineages}"

    input_dict = {
        "DOWNLOAD_WDL_URI": wdl_uri("Download"),
        "COMPRESS_WDL_URI": wdl_uri("Compress"),
        "INDEX_WDL_URI": wdl_uri("Index"),
        "Input": {
            "Download": download_input,
            "Compress": compress_input,
            "Index": index_input,
        },
        "OutputPrefix": f"s3://{bucket}/ncbi-indexes-{deployment_environment}/{index_name}/",
        # Per-stage container memory overrides consumed by the SFN template.
        "DownloadEC2Memory": download_memory,
        "CompressEC2Memory": compress_memory,
        "IndexSPOTMemory": index_spot_memory,
        "IndexEC2Memory": index_ec2_memory,
    }
    sfn.start_execution(
        stateMachineArn=state_machine_arn,
        name=f"index-generation-{index_name}-{uuid4()}",
        input=json.dumps(input_dict),
    )
