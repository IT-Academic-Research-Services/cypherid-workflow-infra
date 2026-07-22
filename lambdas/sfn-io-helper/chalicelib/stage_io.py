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
# Fan-out index-generation (platform-overhaul 800). Nine stages across three phases:
#   Phase 1  DownloadTaxonomy | DownloadNT | DownloadNR                (parallel download lanes)
#   Phase 2  CompressNT->IndexNT | CompressNR->IndexNR | IndexTaxonomy (parallel per-db lanes)
#   Phase 3  Assemble                                                  (cross-db accession join)
# This DAG maps each stage's cross-stage File input to the accumulated-Result output name it
# resolves from (any prior stage's output by bare name). Result accumulates across the whole
# run -- unioned at each parallel-branch boundary by merge_parallel_outputs -- so a lane can
# read another lane's output: CompressNR reads the taxonomy lane's accession2taxid_pdb/prot,
# and Assemble reads both compressed dbs. Within a lane the bare db name (nt/nr) is overwritten
# in Result as download->compress run in sequence, so compress_out_nt resolves to the
# compressed nt by the time the NT index/assemble stages read it.
index_generation_io_map = collections.OrderedDict(
    [
        ("DownloadTaxonomy", {}),
        ("DownloadNT", {}),
        ("DownloadNR", {}),
        (
            "CompressNR",
            {
                "download_out_nr": "nr",
                "download_out_accession2taxid_pdb": "accession2taxid_pdb",
                "download_out_accession2taxid_prot": "accession2taxid_prot",
            },
        ),
        (
            "CompressNT",
            {
                "download_out_nt": "nt",
                "download_out_accession2taxid_nucl_gb": "accession2taxid_nucl_gb",
                "download_out_accession2taxid_nucl_wgs": "accession2taxid_nucl_wgs",
            },
        ),
        ("IndexNR", {"compress_out_nr": "nr"}),
        ("IndexNT", {"compress_out_nt": "nt"}),
        ("IndexTaxonomy", {"taxdump": "taxdump"}),
        (
            "Assemble",
            {
                "compress_out_nt": "nt",
                "compress_out_nr": "nr",
                "accession2taxid_nucl_gb": "accession2taxid_nucl_gb",
                "accession2taxid_nucl_wgs": "accession2taxid_nucl_wgs",
                "accession2taxid_pdb": "accession2taxid_pdb",
                "accession2taxid_prot": "accession2taxid_prot",
            },
        ),
    ]
)

index_generation_stages = list(index_generation_io_map)

# Within-lane sequential handoff: when the KEY stage's ReadOutput completes, the io-helper
# writes the VALUE stage's input from the accumulated Result (the value is the next stage in
# the SAME parallel branch, so the branch's Result is already in scope). Cross-PHASE handoffs
# (Phase-1 downloads -> Phase-2 compress lanes, and Phase-2 lanes -> Assemble) are written by
# merge_parallel_outputs instead, since those cross parallel-branch boundaries where each
# branch holds an isolated copy of Result.
index_generation_lane_successors = {
    "CompressNR": "IndexNR",
    "CompressNT": "IndexNT",
}


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
    """True when the SFN input is the fan-out index-generation pipeline.

    Detected by the per-lane WDL URI keys the start_index_generation lambda emits
    (DOWNLOAD_NR_WDL_URI + ASSEMBLE_WDL_URI), rather than the state machine name, so it does
    not depend on the swipe SFN naming convention.
    """
    return "DOWNLOAD_NR_WDL_URI" in sfn_state and "ASSEMBLE_WDL_URI" in sfn_state


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

    # Determine which stage's input to write now. For the fan-out index-generation pipeline
    # this is the WITHIN-LANE successor (or None -- cross-phase handoffs are done by
    # merge_parallel_outputs at each parallel-branch boundary). For the linear short-read-mngs
    # (idseq_dag) chain it is the next stage in order, as before.
    next_stage = None
    if stages is index_generation_stages:
        next_stage = index_generation_lane_successors.get(stage)
    elif stages is not None and stages.index(stage) < len(stages) - 1:
        next_stage = stages[stages.index(stage) + 1]

    if next_stage:
        _write_stage_input_from_result(sfn_state, next_stage, io_map)
    return sfn_state


def _write_stage_input_from_result(sfn_state, next_stage, io_map):
    """Resolve next_stage's cross-stage File inputs from the accumulated Result via io_map and
    write its input.json. Shared by the linear (idseq_dag) handoff, the fan-out within-lane
    handoff, and merge_parallel_outputs' cross-phase handoff.
    """
    next_stage_input = get_stage_input(sfn_state=sfn_state, stage=next_stage)
    for input_name, result_key in io_map[next_stage].items():
        if input_name.startswith("fastqs"):
            input_uri = sfn_state["Input"]["HostFilter"].get(input_name)
        else:
            input_uri = sfn_state["Result"].get(result_key)
        if input_uri:
            next_stage_input[input_name] = input_uri
        else:
            logger.warning("No output found for I/O map key %s", input_name)
    put_stage_input(sfn_state=sfn_state, stage=next_stage, stage_input=next_stage_input)


def merge_parallel_outputs(branch_states, next_stages):
    """Merge an SFN Parallel state's array of branch states into one state, then write the
    given downstream stages' inputs from the merged Result (the fan-out cross-phase handoff).

    SFN `Parallel` emits `[branch_0_state, branch_1_state, ...]`; each branch ran on an
    isolated copy of the state and accumulated only its own outputs into its Result. This
    unions those Results (and BatchJobDetails) back into a single state so the run's
    accumulated Result is whole again, then writes each next_stage's input.json from it via the
    index-generation io-map -- exactly what read_state_from_s3 does within a lane, but across
    the parallel-branch boundary the per-branch ReadOutput could not see.
    """
    merged = dict(branch_states[0])  # carries the shared _WDL_URI / _INPUT_URI / OutputPrefix keys
    merged_result = {}
    merged_batch_details = {}
    for branch in branch_states:
        merged_result.update(branch.get("Result", {}))
        merged_batch_details.update(branch.get("BatchJobDetails", {}))
    merged["Result"] = merged_result
    merged["BatchJobDetails"] = merged_batch_details
    for stage in next_stages:
        _write_stage_input_from_result(merged, stage, index_generation_io_map)
    return merged


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
        if not _is_index_generation(sfn_state):
            # Fan-out index-generation supplies its four memory tiers (Download/Compress/
            # IndexSPOT/IndexEC2 EC2Memory) directly from the start lambda, and the SFN
            # template reads those tier keys for all nine stages -- so per-stage memory keys
            # (which would need nine new *Default env vars) are not set here for index-gen.
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
        if not _is_index_generation(sfn_state):
            # index-gen sub-WDLs (download/compress/index) do not declare s3_wd_uri,
            # so miniwdl would reject it at input validation. short-read-mngs and the
            # single-stage "Run" workflows do declare String s3_wd_uri and rely on it.
            stage_input.setdefault("s3_wd_uri", output_path)
        put_stage_input(sfn_state=sfn_state, stage=stage, stage_input=stage_input)
    return sfn_state
