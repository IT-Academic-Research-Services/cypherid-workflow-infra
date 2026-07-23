import json
import os
from uuid import uuid4

import boto3

# Fan-out index-generation (platform-overhaul 800, Lever 2). The SFN state machine
# (sfn_templates/index-generation.yml) runs the pipeline as three PHASES with per-database
# lanes fanned out inside phases 1 and 2, instead of one linear Download -> Compress -> Index
# chain:
#
#   Phase 1  Parallel[ DownloadTaxonomy | DownloadNT | DownloadNR ]  -> MergeDownloads
#   Phase 2  Parallel[ CompressNR->IndexNR | CompressNT->IndexNT | IndexTaxonomy ] -> MergeLanes
#   Phase 3  Assemble   (GenerateIndexAccessions -- the one cross-DB task)
#
# core_nt, nr and the taxonomy files download concurrently on their own right-sized boxes
# (799 per-DB queues), then each DB's compress+index lane runs concurrently, so NR's long
# compress overlaps NT's whole path. Wall-clock -> max(lane) instead of sum.
#
# This lambda builds the SFN input in the shape the (extended) SWIPE io-helper consumes:
#   * one per-stage WDL URI (<STAGE>_WDL_URI) for each of the nine sub-WDLs,
#   * a per-stage `Input.<Stage>` payload with ONLY that sub-WDL's declared inputs,
#   * STAGES_IO_MAP_JSON: the DAG output->input handoff map the io-helper resolves from the
#     accumulated run Result (any prior stage's output by bare name), and
#   * the per-stage container-memory overrides the SFN template reads.
#
# The File hand-offs (download_out_* / compress_out_* / accession2taxid_*) are NOT set here:
# the io-helper injects them at runtime from the accumulated Result via STAGES_IO_MAP.

# Sub-WDL filename per stage (seqtoid-workflows index-generation/*.wdl, uploaded to S3 under
# the versioned workflows prefix). Single place to reconcile with the WDL split.
STAGE_WDL_FILENAMES = {
    "DownloadTaxonomy": "download-taxonomy.wdl",
    "DownloadNT": "download-nt.wdl",
    "DownloadNR": "download-nr.wdl",
    "CompressNT": "compress-nt.wdl",
    "CompressNR": "compress-nr.wdl",
    "IndexNT": "index-nt.wdl",
    "IndexNR": "index-nr.wdl",
    "IndexTaxonomy": "index-taxonomy.wdl",
    "Assemble": "assemble.wdl",
}

# DAG output->input handoff map consumed by the io-helper. For each stage,
# `{ <this stage's declared File input>: <accumulated output name to resolve it from> }`.
# Sources are resolved from the run's accumulated Result (union of every completed stage's
# outputs), so a lane can read another lane's output by bare name -- e.g. CompressNR reads the
# taxonomy lane's accession2taxid_pdb/prot. Within a lane the bare db name (nt/nr) is
# overwritten in Result as download->compress->index run in sequence, so `compress_out_nt`
# resolves to the compressed nt by the time the NT index/assemble stages read it.
STAGES_IO_MAP = {
    # Phase 2 compress lanes read their raw db (from the download lane) + their taxid pair
    # (from the taxonomy lane).
    "CompressNR": {
        "download_out_nr": "nr",
        "download_out_accession2taxid_pdb": "accession2taxid_pdb",
        "download_out_accession2taxid_prot": "accession2taxid_prot",
    },
    "CompressNT": {
        "download_out_nt": "nt",
        "download_out_accession2taxid_nucl_gb": "accession2taxid_nucl_gb",
        "download_out_accession2taxid_nucl_wgs": "accession2taxid_nucl_wgs",
    },
    # Phase 2 index lanes read their compressed db (from the compress step in the same lane).
    "IndexNR": {"compress_out_nr": "nr"},
    "IndexNT": {"compress_out_nt": "nt"},
    "IndexTaxonomy": {"taxdump": "taxdump"},
    # Phase 3 assemble reads both compressed dbs + all four accession2taxid files.
    "Assemble": {
        "compress_out_nt": "nt",
        "compress_out_nr": "nr",
        "accession2taxid_nucl_gb": "accession2taxid_nucl_gb",
        "accession2taxid_nucl_wgs": "accession2taxid_nucl_wgs",
        "accession2taxid_pdb": "accession2taxid_pdb",
        "accession2taxid_prot": "accession2taxid_prot",
    },
}


def start_index_generation(event, *args):
    deployment_environment = os.environ["DEPLOYMENT_ENVIRONMENT"]
    state_machine_arn = os.environ["INDEX_GENERATION_SFN_ARN"]
    version = os.environ["INDEX_GENERATION_WORKFLOW_VERSION"]
    aws_region = os.environ["AWS_REGION"]
    aws_account_id = os.environ["AWS_ACCOUNT_ID"]
    bucket = os.environ["BUCKET"]
    workflows_bucket = os.environ["S3_WORKFLOWS_BUCKET"]

    # Per-stage container memory (MB). The SFN template reads these per lane/phase.
    download_memory = int(os.environ["DOWNLOAD_MEMORY"])
    compress_memory = int(os.environ["COMPRESS_MEMORY"])
    index_spot_memory = int(os.environ["INDEX_SPOT_MEMORY"])
    index_ec2_memory = int(os.environ["INDEX_EC2_MEMORY"])

    # Optional overrides the caller (or a scheduled trigger) can set on the event to steer a
    # run without a code change:
    #   provided_nr / provided_nt  -- reuse an existing .fsa and skip that download (salvage /
    #                                 resume; e.g. the recovered 530GB nr.fsa).
    #   nt_database_type           -- "nt" (default) or "core_nt".
    #   skip_protein_compression / skip_nuc_compression -- pass through to the compress lanes.
    overrides = event.get("index_generation", {}) if isinstance(event, dict) else {}
    provided_nr = overrides.get("provided_nr")
    provided_nt = overrides.get("provided_nt")
    nt_database_type = overrides.get("nt_database_type", "nt")

    sfn = boto3.client("stepfunctions")
    s3 = boto3.client("s3")

    # Seed the taxonomy lineage build + the compress lanes incrementally from the most recent
    # prior run, if any (Lever 4 -- unchanged inputs cache-hit; a seeded compress only builds
    # the delta).
    previous_lineages = None
    previous_nt_compressed = None
    previous_nr_compressed = None
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
            elif key.endswith("nt_compressed.fa") and (
                not previous_nt_compressed or key > previous_nt_compressed
            ):
                previous_nt_compressed = key
            elif key.endswith("nr_compressed.fa") and (
                not previous_nr_compressed or key > previous_nr_compressed
            ):
                previous_nr_compressed = key

    index_name = event["time"][:10]
    docker_image_id = f"{aws_account_id}.dkr.ecr.{aws_region}.amazonaws.com/index-generation:{version}"
    output_prefix = f"s3://{bucket}/ncbi-indexes-{deployment_environment}/{index_name}/"

    def wdl_uri(stage):
        return f"s3://{workflows_bucket}/index-generation-{version}/{STAGE_WDL_FILENAMES[stage]}"

    def s3_uri(key):
        return f"s3://{bucket}/{key}"

    # Publish the DAG handoff map so the io-helper can resolve it.
    stage_io_map_key = f"ncbi-indexes-{deployment_environment}/{index_name}/stage_io_map.json"
    s3.put_object(Bucket=bucket, Key=stage_io_map_key, Body=json.dumps(STAGES_IO_MAP).encode())

    # Per-stage inputs: ONLY each sub-WDL's declared workflow inputs. The File hand-offs are
    # injected at runtime via STAGES_IO_MAP, so they are omitted here.
    download_nt_input = {"docker_image_id": docker_image_id, "nt_database_type": nt_database_type}
    if provided_nt:
        download_nt_input["provided_nt"] = provided_nt

    download_nr_input = {"docker_image_id": docker_image_id}
    if provided_nr:
        download_nr_input["provided_nr"] = provided_nr

    compress_nt_input = {"docker_image_id": docker_image_id}
    if previous_nt_compressed:
        compress_nt_input["previous_nt_compressed"] = s3_uri(previous_nt_compressed)
    if "skip_nuc_compression" in overrides:
        compress_nt_input["skip_nuc_compression"] = overrides["skip_nuc_compression"]

    compress_nr_input = {"docker_image_id": docker_image_id}
    if previous_nr_compressed:
        compress_nr_input["previous_nr_compressed"] = s3_uri(previous_nr_compressed)
    if "skip_protein_compression" in overrides:
        compress_nr_input["skip_protein_compression"] = overrides["skip_protein_compression"]

    index_taxonomy_input = {"docker_image_id": docker_image_id, "index_name": index_name}
    if previous_lineages:
        index_taxonomy_input["previous_lineages"] = s3_uri(previous_lineages)

    stage_inputs = {
        "DownloadTaxonomy": {"docker_image_id": docker_image_id},
        "DownloadNT": download_nt_input,
        "DownloadNR": download_nr_input,
        "CompressNT": compress_nt_input,
        "CompressNR": compress_nr_input,
        "IndexNT": {"docker_image_id": docker_image_id},
        "IndexNR": {"docker_image_id": docker_image_id},
        "IndexTaxonomy": index_taxonomy_input,
        "Assemble": {"docker_image_id": docker_image_id},
    }

    input_dict = {
        **{f"{_uri_key(stage)}": wdl_uri(stage) for stage in STAGE_WDL_FILENAMES},
        "STAGES_IO_MAP_JSON": s3_uri(stage_io_map_key),
        "Input": stage_inputs,
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


def _uri_key(stage):
    """<STAGE>_WDL_URI env key for a stage name. Splits on camelCase boundaries but keeps
    acronyms intact: DownloadNT -> DOWNLOAD_NT, IndexTaxonomy -> INDEX_TAXONOMY,
    Assemble -> ASSEMBLE (underscore only before an uppercase that follows a lowercase)."""
    out = []
    for i, ch in enumerate(stage):
        if ch.isupper() and i > 0 and not stage[i - 1].isupper():
            out.append("_")
        out.append(ch.upper())
    return "".join(out) + "_WDL_URI"
