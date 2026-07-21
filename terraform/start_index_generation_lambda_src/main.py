import json
import os
from uuid import uuid4

import boto3

# Multi-stage index-generation (Lever 1, Track A). The SFN state machine
# (sfn_templates/index-generation.yml) runs three right-sized phase stages -- Download,
# Compress, Index -- instead of one monolithic RunEC2 job. This lambda builds the SFN input
# in the exact shape the deployed SWIPE io-helper (module.swipe sfn_io_helper) consumes:
#
#   * one per-stage WDL URI (DOWNLOAD_WDL_URI / COMPRESS_WDL_URI / INDEX_WDL_URI),
#   * a per-stage `Input.<Stage>` payload carrying ONLY that sub-WDL's declared workflow
#     inputs (no undeclared keys -- miniwdl rejects those),
#   * STAGES_IO_MAP_JSON: the stage-to-stage output->input handoff map the io-helper's
#     link_outputs uses to thread each stage's miniwdl outputs into the next stage's File
#     inputs (Download outputs -> Compress inputs -> Index inputs), and
#   * the per-stage container-memory overrides the SFN template reads
#     ($.DownloadEC2Memory / $.CompressEC2Memory / $.IndexSPOTMemory / $.IndexEC2Memory).
#
# The File hand-offs (download_out_* / compress_out_*) are NOT set here: they are populated
# at runtime by the io-helper from the prior stage's outputs via STAGES_IO_MAP below, so the
# per-stage inputs intentionally omit them.

# Sub-WDL filename per stage, resolved under the versioned workflows prefix. Single place to
# reconcile with the seqtoid-workflows WDL split (download.wdl / compress.wdl / index.wdl).
STAGE_WDL_FILENAMES = {
    "Download": "download.wdl",
    "Compress": "compress.wdl",
    "Index": "index.wdl",
}

# Stage-to-stage output->input handoff map consumed by the io-helper's link_outputs.
# For each downstream stage, `{ <this stage's input name>: <prior stage's output name> }`.
# Verified against the seqtoid-workflows sub-WDLs (index-generation/{download,compress,index}.wdl):
#   download.wdl outputs: nt, nr, accession2taxid_nucl_gb/_nucl_wgs/_pdb/_prot, taxdump
#   compress.wdl outputs: nt, nr, accession2taxid_nucl_gb/_nucl_wgs/_pdb/_prot, taxdump
# so Compress reads download_out_* and Index reads compress_out_*.
_PASSTHROUGH = [
    "nt",
    "nr",
    "accession2taxid_nucl_gb",
    "accession2taxid_nucl_wgs",
    "accession2taxid_pdb",
    "accession2taxid_prot",
    "taxdump",
]
STAGES_IO_MAP = {
    "Compress": {f"download_out_{name}": name for name in _PASSTHROUGH},
    "Index": {f"compress_out_{name}": name for name in _PASSTHROUGH},
}


def start_index_generation(event, *args):
    deployment_environment = os.environ["DEPLOYMENT_ENVIRONMENT"]
    state_machine_arn = os.environ["INDEX_GENERATION_SFN_ARN"]
    version = os.environ["INDEX_GENERATION_WORKFLOW_VERSION"]
    aws_region = os.environ["AWS_REGION"]
    aws_account_id = os.environ["AWS_ACCOUNT_ID"]
    bucket = os.environ["BUCKET"]
    workflows_bucket = os.environ["S3_WORKFLOWS_BUCKET"]

    # Per-stage container memory (MB). The SFN template reads these as
    # $.DownloadEC2Memory / $.CompressEC2Memory / $.IndexSPOTMemory / $.IndexEC2Memory.
    download_memory = int(os.environ["DOWNLOAD_MEMORY"])
    compress_memory = int(os.environ["COMPRESS_MEMORY"])
    index_spot_memory = int(os.environ["INDEX_SPOT_MEMORY"])
    index_ec2_memory = int(os.environ["INDEX_EC2_MEMORY"])

    sfn = boto3.client("stepfunctions")
    s3 = boto3.client("s3")

    # Seed the Index stage's incremental lineage build from the most recent prior run, if any.
    previous_lineages = None
    pages = s3.get_paginator("list_objects_v2").paginate(
        Bucket=bucket,
        Prefix=f"ncbi-indexes-{deployment_environment}/",
    )
    for page in pages:
        for obj in page.get("Contents", []):
            key = obj["Key"]
            if key.endswith("versioned-taxid-lineages.csv.gz") and (
                not previous_lineages or key > previous_lineages
            ):
                previous_lineages = key

    index_name = event["time"][:10]
    docker_image_id = f"{aws_account_id}.dkr.ecr.{aws_region}.amazonaws.com/index-generation:{version}"
    output_prefix = f"s3://{bucket}/ncbi-indexes-{deployment_environment}/{index_name}/"

    def wdl_uri(stage):
        return f"s3://{workflows_bucket}/index-generation-{version}/{STAGE_WDL_FILENAMES[stage]}"

    # Publish the stage handoff map so the io-helper's link_outputs can resolve it. Written
    # under the run's OutputPrefix so it is co-located with the per-stage input/output JSONs.
    stage_io_map_key = f"ncbi-indexes-{deployment_environment}/{index_name}/stage_io_map.json"
    s3.put_object(
        Bucket=bucket,
        Key=stage_io_map_key,
        Body=json.dumps(STAGES_IO_MAP).encode(),
    )
    stage_io_map_uri = f"s3://{bucket}/{stage_io_map_key}"

    # Per-stage inputs: ONLY each sub-WDL's declared workflow inputs. provided_nt/provided_nr
    # are intentionally omitted so Download pulls the full NT/NR from NCBI (the accession2taxid
    # and taxdump inputs default to their NCBI URLs in download.wdl). The File hand-offs
    # (download_out_* / compress_out_*) are injected at runtime via STAGES_IO_MAP.
    index_input = {
        "docker_image_id": docker_image_id,
        "index_name": index_name,
    }
    if previous_lineages:
        index_input["previous_lineages"] = f"s3://{bucket}/{previous_lineages}"

    input_dict = {
        "DOWNLOAD_WDL_URI": wdl_uri("Download"),
        "COMPRESS_WDL_URI": wdl_uri("Compress"),
        "INDEX_WDL_URI": wdl_uri("Index"),
        "STAGES_IO_MAP_JSON": stage_io_map_uri,
        "Input": {
            "Download": {"docker_image_id": docker_image_id},
            "Compress": {"docker_image_id": docker_image_id},
            "Index": index_input,
        },
        "OutputPrefix": output_prefix,
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
