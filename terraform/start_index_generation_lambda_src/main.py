import json
import os
import re
from uuid import uuid4

import boto3

# Multi-stage index-generation (Lever 1, Track A). The SFN state machine
# (sfn_templates/index-generation.yml) now runs three right-sized phase stages -- Download,
# Compress, Index -- instead of one monolithic RunEC2 job. This lambda builds the per-stage
# SFN input: a per-stage WDL URI, a per-stage Input payload, and the per-stage container
# memory overrides the template consumes ($.DownloadEC2Memory, $.CompressEC2Memory,
# $.IndexSPOTMemory, $.IndexEC2Memory).
#
# UPSTREAM DEPENDENCY (seqtoid-workflows WDL split PR): a SWIPE stage runs a WHOLE WDL
# locally, so each stage needs its own sub-WDL (download.wdl / compress.wdl / index.wdl)
# built into the index-generation image and uploaded to the workflows bucket. Until that
# lands, the URIs below resolve to files that do not exist yet and the pipeline cannot run
# end-to-end -- the infra is authored to consume them. The EXACT per-stage Input keys each
# sub-WDL reads (and the S3 hand-off URIs between Compress and Index) are defined by those
# sub-WDLs and must be reconciled here when they land; the payloads below carry the common
# run inputs as the starting contract.

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

    major_version = re.search(r"v(\d+)\..+", version).group(1)

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
    s3_dir = f"s3://{bucket}/ncbi-indexes-{deployment_environment}/{index_name}/index-generation-{major_version}"

    def wdl_uri(stage):
        return f"s3://{workflows_bucket}/index-generation-{version}/{STAGE_WDL_FILENAMES[stage]}"

    # Common run inputs shared by every stage. The per-stage sub-WDLs (seqtoid-workflows WDL
    # split) will consume the subset each phase needs; reconcile exact keys when they land.
    common_run_input = {
        "docker_image_id": f"{aws_account_id}.dkr.ecr.{aws_region}.amazonaws.com/index-generation:{version}",
        "write_to_db": True,
        "index_name": index_name,
        "env": deployment_environment,
        "s3_dir": s3_dir,
        "previous_lineages": f"s3://{bucket}/{previous_lineages}",
    }

    input_dict = {
        "DOWNLOAD_WDL_URI": wdl_uri("Download"),
        "COMPRESS_WDL_URI": wdl_uri("Compress"),
        "INDEX_WDL_URI": wdl_uri("Index"),
        "Input": {
            "Download": dict(common_run_input),
            "Compress": dict(common_run_input),
            "Index": dict(common_run_input),
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
