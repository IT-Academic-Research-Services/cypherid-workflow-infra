import os
import re
import json
import logging
import collections

from botocore import xform_name

from . import s3_object

logger = logging.getLogger()

idseq_dag_io_map = collections.OrderedDict(
    [
        ("HostFilter", {"fastqs_0": None, "fastqs_1": None}),
        (
            "NonHostAlignment",
            {
                "host_filter_out_gsnap_filter_1_fa": "gsnap_filter_out_gsnap_filter_1_fa",
                "host_filter_out_gsnap_filter_2_fa": "gsnap_filter_out_gsnap_filter_2_fa",
                "host_filter_out_gsnap_filter_merged_fa": "gsnap_filter_out_gsnap_filter_merged_fa",
                "duplicate_cluster_sizes_tsv": "czid_dedup_out_duplicate_cluster_sizes_tsv",
                "czid_dedup_out_duplicate_clusters_csv": "czid_dedup_out_duplicate_clusters_csv",
            },
        ),
        (
            "Postprocess",
            {
                "host_filter_out_gsnap_filter_1_fa": "gsnap_filter_out_gsnap_filter_1_fa",
                "host_filter_out_gsnap_filter_2_fa": "gsnap_filter_out_gsnap_filter_2_fa",
                "host_filter_out_gsnap_filter_merged_fa": "gsnap_filter_out_gsnap_filter_merged_fa",
                "gsnap_out_gsnap_m8": "gsnap_out_gsnap_m8",
                "gsnap_out_gsnap_deduped_m8": "gsnap_out_gsnap_deduped_m8",
                "gsnap_out_gsnap_hitsummary_tab": "gsnap_out_gsnap_hitsummary_tab",
                "gsnap_out_gsnap_counts_with_dcr_json": "gsnap_out_gsnap_counts_with_dcr_json",
                "rapsearch2_out_rapsearch2_m8": "rapsearch2_out_rapsearch2_m8",
                "rapsearch2_out_rapsearch2_deduped_m8": "rapsearch2_out_rapsearch2_deduped_m8",
                "rapsearch2_out_rapsearch2_hitsummary_tab": "rapsearch2_out_rapsearch2_hitsummary_tab",
                "rapsearch2_out_rapsearch2_counts_with_dcr_json": "rapsearch2_out_rapsearch2_counts_with_dcr_json",  # noqa
                "duplicate_cluster_sizes_tsv": "czid_dedup_out_duplicate_cluster_sizes_tsv",
                "czid_dedup_out_duplicate_clusters_csv": "czid_dedup_out_duplicate_clusters_csv",
            },
        ),
        (
            "Experimental",
            {
                "taxid_fasta_in_annotated_merged_fa": "refined_annotated_out_assembly_refined_annotated_merged_fa",  # noqa
                "taxid_fasta_in_gsnap_hitsummary_tab": "gsnap_out_gsnap_hitsummary_tab",
                "taxid_fasta_in_rapsearch2_hitsummary_tab": "rapsearch2_out_rapsearch2_hitsummary_tab",
                "gsnap_m8_gsnap_deduped_m8": "gsnap_out_gsnap_deduped_m8",
                "refined_gsnap_in_gsnap_reassigned_m8": "refined_gsnap_out_assembly_gsnap_reassigned_m8",
                "refined_gsnap_in_gsnap_hitsummary2_tab": "refined_gsnap_out_assembly_gsnap_hitsummary2_tab",
                "refined_gsnap_in_gsnap_blast_top_m8": "refined_gsnap_out_assembly_gsnap_blast_top_m8",
                "contig_in_contig_coverage_json": "coverage_out_assembly_contig_coverage_json",
                "contig_in_contig_stats_json": "assembly_out_assembly_contig_stats_json",
                "contig_in_contigs_fasta": "assembly_out_assembly_contigs_fasta",
                "fastqs_0": None,
                "fastqs_1": None,
                "nonhost_fasta_refined_taxid_annot_fasta": "refined_taxid_fasta_out_assembly_refined_taxid_annot_fasta",  # noqa
                "duplicate_clusters_csv": "czid_dedup_out_duplicate_clusters_csv",
            },
        ),
    ]
)

idseq_dag_stages = list(idseq_dag_io_map)

# Multi-stage index-generation (Lever 1, Track A). The index-generation SFN
# (terraform/sfn_templates/index-generation.yml) runs three right-sized phase stages --
# Download -> Compress -> Index -- each a whole sub-WDL (download.wdl / compress.wdl /
# index.wdl in seqtoid-workflows). Mirroring idseq_dag_io_map above, this maps each stage's
# cross-stage `<prev>_out_<name>` input to the identically named output of the immediately
# preceding stage (the 1:1 name map defined by index-generation-STAGE-SPLIT.md). Download
# takes no upstream handoff (its inputs are optional NCBI URLs defaulted in the sub-WDL);
# Compress reads the seven Download outputs; Index reads the seven Compress outputs. The
# accession2taxid_* + taxdump small files are passed through Compress unchanged so the
# linear chain only ever hands off to the immediately following stage.
index_generation_io_map = collections.OrderedDict(
    [
        ("Download", {}),
        (
            "Compress",
            {
                "download_out_nt": "nt",
                "download_out_nr": "nr",
                "download_out_accession2taxid_nucl_gb": "accession2taxid_nucl_gb",
                "download_out_accession2taxid_nucl_wgs": "accession2taxid_nucl_wgs",
                "download_out_accession2taxid_pdb": "accession2taxid_pdb",
                "download_out_accession2taxid_prot": "accession2taxid_prot",
                "download_out_taxdump": "taxdump",
            },
        ),
        (
            "Index",
            {
                "compress_out_nt": "nt",
                "compress_out_nr": "nr",
                "compress_out_accession2taxid_nucl_gb": "accession2taxid_nucl_gb",
                "compress_out_accession2taxid_nucl_wgs": "accession2taxid_nucl_wgs",
                "compress_out_accession2taxid_pdb": "accession2taxid_pdb",
                "compress_out_accession2taxid_prot": "accession2taxid_prot",
                "compress_out_taxdump": "taxdump",
            },
        ),
    ]
)

index_generation_stages = list(index_generation_io_map)


def _pipeline_for_stage(stage):
    """Return the (stages, io_map) pair the given stage belongs to, or (None, None).

    Lets read_state_from_s3 drive both the short-read-mngs (idseq_dag) and the
    index-generation multi-stage hand-offs through one code path.
    """
    if stage in idseq_dag_stages:
        return idseq_dag_stages, idseq_dag_io_map
    if stage in index_generation_stages:
        return index_generation_stages, index_generation_io_map
    return None, None


def _is_index_generation(sfn_state):
    """True when the SFN input is the multi-stage index-generation pipeline.

    Detected by the per-stage WDL URI keys the start_index_generation lambda emits
    (DOWNLOAD_WDL_URI / COMPRESS_WDL_URI / INDEX_WDL_URI), rather than the state machine
    name, so it does not depend on the swipe SFN naming convention.
    """
    return "DOWNLOAD_WDL_URI" in sfn_state and "INDEX_WDL_URI" in sfn_state


def get_input_uri_key(stage):
    return f"{xform_name(stage).upper()}_INPUT_URI"


def get_output_uri_key(stage):
    return f"{xform_name(stage).upper()}_OUTPUT_URI"


def get_stage_input(sfn_state, stage):
    input_uri = sfn_state[get_input_uri_key(stage)]
    return json.loads(s3_object(input_uri).get()["Body"].read().decode())


def put_stage_input(sfn_state, stage, stage_input):
    input_uri = sfn_state[get_input_uri_key(stage)]
    s3_object(input_uri).put(Body=json.dumps(stage_input).encode())


def get_stage_output(sfn_state, stage):
    output_uri = sfn_state[get_output_uri_key(stage)]
    return json.loads(s3_object(output_uri).get()["Body"].read().decode())


def read_state_from_s3(sfn_state, current_state):
    stage = current_state.replace("ReadOutput", "")
    sfn_state.setdefault("Result", {})
    stage_output = get_stage_output(sfn_state, stage)

    # Extract Batch job error, if any, and drop error metadata to avoid overrunning the Step Functions state size limit
    batch_job_error = sfn_state.pop("BatchJobError", {})
    # If the stage succeeded, don't throw an error
    if not sfn_state.get("BatchJobDetails", {}).get(stage):
        if batch_job_error and next(iter(batch_job_error)).startswith(stage):
            error_type = type(stage_output["error"], (Exception,), dict())
            raise error_type(stage_output["cause"])

    # Multi-stage pipelines (short-read-mngs idseq_dag, index-generation) namespace each
    # workflow output as `<workflow_name>.<output>`; strip that prefix so the I/O map can
    # resolve the next stage's `<prev>_out_<name>` inputs by bare output name.
    stages, io_map = _pipeline_for_stage(stage)
    if stages is not None:
        stage_output = {
            k.split(".", 1)[1]: v
            for k, v in stage_output.items()
            if not isinstance(v, list)
        }
    sfn_state["Result"].update(stage_output)

    if stages is not None and stages.index(stage) < len(stages) - 1:
        next_stage = stages[stages.index(stage) + 1]
        next_stage_input = get_stage_input(sfn_state=sfn_state, stage=next_stage)
        for input_name, result_key in io_map[next_stage].items():  # type: ignore
            if input_name.startswith("fastqs"):
                input_uri = sfn_state["Input"]["HostFilter"].get(input_name)
            else:
                input_uri = sfn_state["Result"].get(result_key)
            if input_uri:
                next_stage_input[input_name] = input_uri
            else:
                logger.warning("No output found for I/O map key %s", input_name)
        put_stage_input(
            sfn_state=sfn_state, stage=next_stage, stage_input=next_stage_input
        )
    return sfn_state


def trim_batch_job_details(sfn_state):
    """
    Remove large redundant batch job description items from Step Function state to avoid overrunning the Step Functions
    state size limit.
    """
    for job_details in sfn_state["BatchJobDetails"].values():
        job_details["Attempts"] = []
        job_details["Container"] = {}
    return sfn_state


def get_workflow_name(sfn_state):
    for k, v in sfn_state.items():
        if k.endswith("_WDL_URI"):
            # TODO: This is extremely hackish; trying to determine the name of the workflow based on what buck it is in!
            #  Since the old bucket is hardcoded, without an easy way of passing in the actual Prod bucket name,
            #  so we again hardcode it!
            if (
                s3_object(v).bucket_name == "cypherid-samples-deleteme"
                or s3_object(v).bucket_name.startswith("seqtoid-workflows-")
            ):
                return os.path.dirname(s3_object(v).key)
            else:
                return os.path.splitext(os.path.basename(s3_object(v).key))[0]


def preprocess_sfn_input(sfn_state, aws_region, aws_account_id, state_machine_name):
    # TODO: add input validation assertions here (use JSON schema?)
    assert sfn_state["OutputPrefix"].startswith("s3://")
    output_prefix = sfn_state["OutputPrefix"]
    output_path = os.path.join(
        output_prefix,
        re.sub(r"v(\d+)\..+", r"\1", get_workflow_name(sfn_state)),
    )
    if _is_index_generation(sfn_state):
        # Multi-stage index-generation: Download -> Compress -> Index. Each stage's
        # INPUT/OUTPUT URI keys are set below so the SFN template can read
        # $.DOWNLOAD_INPUT_URI / $.COMPRESS_OUTPUT_URI / etc., and the cross-stage
        # download_out_* / compress_out_* hand-off is wired by read_state_from_s3.
        stages = index_generation_stages
    elif re.match(r"idseq-\w+-main-\d+", state_machine_name):
        stages = idseq_dag_stages
    else:
        stages = ["Run"]
    for stage in stages:
        sfn_state[get_input_uri_key(stage)] = os.path.join(
            output_path, f"{xform_name(stage)}_input.json"
        )
        sfn_state[get_output_uri_key(stage)] = os.path.join(
            output_path, f"{xform_name(stage)}_output.json"
        )
        for compute_env in "SPOT", "EC2":
            memory_key = stage + compute_env + "Memory"
            sfn_state.setdefault(memory_key, int(os.environ[memory_key + "Default"]))
        stage_input = sfn_state["Input"].get(stage, {})
        ecr_repo = f"{aws_account_id}.dkr.ecr.{aws_region}.amazonaws.com"
        workflow_name, workflow_version = get_workflow_name(sfn_state).rsplit("-v", 1)
        default_docker_image_id = (
            f"{ecr_repo}/idseq-{workflow_name}:v{workflow_version}"
        )
        stage_input.setdefault("docker_image_id", default_docker_image_id)
        stage_input.setdefault("s3_wd_uri", output_path)
        put_stage_input(sfn_state=sfn_state, stage=stage, stage_input=stage_input)
    return sfn_state
