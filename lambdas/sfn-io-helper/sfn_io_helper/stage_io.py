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

    if stage in idseq_dag_stages:
        stage_output = {
            k.split(".", 1)[1]: v
            for k, v in stage_output.items()
            if not isinstance(v, list)
        }
    sfn_state["Result"].update(stage_output)

    if (
        stage in idseq_dag_stages
        and idseq_dag_stages.index(stage) < len(idseq_dag_stages) - 1
    ):
        next_stage = idseq_dag_stages[idseq_dag_stages.index(stage) + 1]
        next_stage_input = get_stage_input(sfn_state=sfn_state, stage=next_stage)
        for input_name, result_key in idseq_dag_io_map[next_stage].items():  # type: ignore
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
            if s3_object(v).bucket_name == "idseq-workflows":
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
    stages = (
        idseq_dag_stages
        if re.match(r"idseq-\w+-main-\d+", state_machine_name)
        else ["Run"]
    )
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
