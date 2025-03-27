#!/usr/bin/env python3

import os
import sys
from uuid import uuid4
import git
import boto3
import json
import logging
import argparse
import datetime
from os import path
from glob import glob
from subprocess import run
from base64 import b64decode
from functools import lru_cache
from tempfile import TemporaryDirectory
from urllib.parse import urlparse

import requests

from aegea.sfn import watch, watch_parser
from aegea.util import Timestamp
from aegea.util.aws import ARN
from aegea.util.printing import YELLOW, RED, GREEN, BOLD, ENDC


class BranchRun:
    def __init__(self, workflow_name, branch):
        logger.info("initializing branch pipeline run")
        self.workflow_name = workflow_name
        self.branch = branch

        self.repo_uri = "https://github.com/chanzuckerberg/czid-workflows.git"
        self.workflows_bucket_name = "idseq-workflows"
        self.branch_workflows_prefix = f"{workflow_name}-v-branch-{branch}"

        self.docker_registry = os.getenv("DOCKER_REGISTRY")
        assert self.docker_registry, "DOCKER_REGISTRY not set, try running appropriate `source environment`"
        self.aws_default_region = os.getenv("AWS_DEFAULT_REGION")
        assert self.aws_default_region, "AWS_DEFAULT_REGION not set, try running appropriate `source environment`"

        self.docker_image_name = f"{workflow_name}"
        docker_image = os.path.join(self.docker_registry, self.docker_image_name)
        self.docker_image_tag = f"branch-{branch}"
        self.docker_image_id = f"{docker_image}:{self.docker_image_tag}"

        self.ecr_client = boto3.client("ecr")
        sess = boto3.session.Session(profile_name='idseq-prod')
        s3 = sess.resource("s3")
        self.workflows_bucket = s3.Bucket(self.workflows_bucket_name)

        self.wdl_s3_objects = []
        with TemporaryDirectory() as git_dir:
            logger.info(f"  cloning branch: {branch}")
            git.Repo.clone_from(self.repo_uri, git_dir, branch=branch, depth=1, single_branch=True)

            logger.info(
                f"  uploading wdl workflows to s3://{self.workflows_bucket_name}/{self.branch_workflows_prefix}"
            )
            for wdl_file in glob(os.path.join(git_dir, workflow_name, "*.wdl")):
                s3_wdl_object = os.path.join(self.branch_workflows_prefix, os.path.basename(wdl_file))
                self.workflows_bucket.upload_file(wdl_file, s3_wdl_object, ExtraArgs={'ACL': 'public-read'})
                self.wdl_s3_objects.append(s3_wdl_object)

            logger.info("  fetching docker credentials from ECR")
            ecr_auth_token = self.ecr_client.get_authorization_token()["authorizationData"][0]["authorizationToken"]
            docker_username, docker_password = b64decode(ecr_auth_token).decode().split(":")

            logger.info("  logging into ECR")
            run([
                "docker", "login",
                "--username", docker_username,
                "--password-stdin", self.docker_registry
            ], input=docker_password.encode(), check=True)

            logger.info(f"  building docker image: {self.docker_image_id}")
            run(["docker", "build", "-t", self.docker_image_id, os.path.join(git_dir, workflow_name)], check=True)

            logger.info(f"  pushing docker image: {self.docker_image_id}")
            run(["docker", "push", self.docker_image_id], check=True)

    def __enter__(self):
        return self

    def __exit__(self, type, value, traceback):
        self.cleanup()

    def cleanup(self):
        logger.info("cleaning up after branch run")

        logger.info(f"  deleting WDL workflows from s3://{self.workflows_bucket_name}/{self.branch_workflows_prefix}")
        for wdl_s3_object in self.wdl_s3_objects:
            self.workflows_bucket.Object(wdl_s3_object).delete()

        logger.info(f"  deleting docker image from ECR: {self.docker_image_id}")
        self.ecr_client.batch_delete_image(
            repositoryName=self.docker_image_name,
            imageIds=[{'imageTag': self.docker_image_tag}]
        )

    @property
    def wdl_uri_by_stage(self):
        def parse_stage(key):
            return os.path.basename(key)[:-len('.wdl')]

        def s3_path(key):
            return f"s3://{self.workflows_bucket_name}/{key}"

        return {
            parse_stage(wdl_s3_object): s3_path(wdl_s3_object) for wdl_s3_object in self.wdl_s3_objects
        }


def print_log_line(event):
    def format_log_level(level):
        log_colors = dict(ERROR=BOLD() + RED(), WARNING=YELLOW(), NOTICE=GREEN())
        if level == "VERBOSE":
            return ""
        elif level in log_colors:
            return " " + log_colors[level] + level + ENDC()
        return level
    try:
        if "aws sts get-caller-identity" in event["message"]:
            return
        ts = Timestamp(event["timestamp"]).astimezone()
        event.update(json.loads(event["message"]))
        for field in "levelno", "timestamp", "ingestionTime":
            event.pop(field, None)
        if event.get("source", "").endswith(".stderr"):
            if "data" in event or "aws sts get-caller-identity" in event.get("message", ""):
                return
            print(ts, event.pop("source", "") + format_log_level(event.pop("level", "")), event.pop("message"))
    except (TypeError, json.decoder.JSONDecodeError):
        print(Timestamp(event["timestamp"]).astimezone(), event["message"])


@lru_cache()
def find_host_filter_index(host_genome, index_type, database_bucket_name="czid-public-references"):
    assert index_type in {"bowtie2_genome.tar", "STAR_genome.tar"}
    index_obj = None
    for obj in s3.Bucket(database_bucket_name).objects.filter(Prefix=f"host_filter/{host_genome}"):
        if obj.key.endswith(index_type):
            index_obj = obj
    return f"s3://{database_bucket_name}/{index_obj.key}"


logging.basicConfig(level=logging.INFO)

logger = logging.getLogger("idseq_dispatch")

parser = argparse.ArgumentParser("run_sfn", description="Run the idseq SFN-WDL pipeline on an idseq sample")
parser.add_argument("--project", help="project ID, used to construct the --sample-dir with --sample if not supplied",
                    default=None)
parser.add_argument("--sample", help="sample ID, used to construct the --sample-dir with --project if not supplied",
                    default=None)
parser.add_argument("--environment", default=os.environ.get("DEPLOYMENT_ENVIRONMENT"))
parser.add_argument("--pipeline-run", default="0")
parser.add_argument("--sample-dir", default=None, help=("s3 directory where samples are located under /fastqs (can be "
                                                        "substituted for --project + --sample)"))
parser.add_argument("--output-dir", help="output directory within sample-dir for results", default="results")
parser.add_argument("--workflow-name", default="short-read-mngs")
parser.add_argument("--czid-workflows-branch")
parser.add_argument("--workflow-version")
parser.add_argument("--sfn-name")
parser.add_argument("--sfn-arn")
parser.add_argument("--stages", nargs="+")
parser.add_argument("--host-genome", default="human")
parser.add_argument("--max-input-fragments", default=9000)
parser.add_argument("--max-subsample-fragments", default=9000)
parser.add_argument("--adapter-fasta",
                    default="s3://czid-public-references/adapter_sequences/illumina_TruSeq3-PE-2_NexteraPE-PE.fasta")
# TODO: make this smarter somehow
parser.add_argument("--index-version", default="2021-01-22")
parser.add_argument("--no-deuterostome-filter", action="store_false", dest="use_deuterostome_filter")
parser.add_argument("--use-taxon-whitelist", action="store_true", dest="use_taxon_whitelist")
parser.add_argument("--sfn-input", type=json.loads, default={})
args = parser.parse_args()

# more complicated argument assertions
if (args.project or args.sample) and args.sample_dir:
    logger.warn("--sample-dir provided alongside project or sample, project and sample will be ignored")
elif not (args.project and args.sample) and not args.sample_dir:
    logger.critical("--sample-dir or both --project and --sample are required")
    exit(1)
parsed_sample_dir = urlparse(args.sample_dir) if args.sample_dir else None
if parsed_sample_dir:
    assert parsed_sample_dir.scheme == "s3", "--sample-dir must be an s3 path like s3://my-bucket/my-prefix"
    assert parsed_sample_dir.path not in {"/", ""}, "--sample-dir must not be the root of an s3 bucket"

s3 = boto3.resource("s3")
if args.environment == "test":
    sfn = boto3.client("stepfunctions", endpoint_url="http://localhost:8083")
    logs = boto3.client("logs", endpoint_url="http://localhost:9000")
    batch = boto3.client("batch", endpoint_url="http://localhost:9000")
else:
    sfn = boto3.client("stepfunctions")
    logs = boto3.client("logs")
    batch = boto3.client("batch")

if args.sfn_name is None:
    args.sfn_name = "short-read-mngs" if args.workflow_name == "short-read-mngs" else "default"

if args.workflow_name == "short-read-mngs":
    index_manifest_key = path.join(path.dirname(boto3.client("s3").list_objects_v2(
        Bucket="czid-public-references",
        MaxKeys=1,
        Prefix=f"ncbi-indexes-prod/{args.index_version}/",
    )["Contents"][0]["Key"]), "run_output.json")
    index_manifest = json.loads(
        s3.Object("czid-public-references", index_manifest_key).get()["Body"].read().decode().strip()
    )

if args.stages is None:
    if args.workflow_name == "short-read-mngs":
        args.stages = ["host_filter", "non_host_alignment", "postprocess", "experimental"]
    else:
        args.stages = ["run"]

if args.sfn_arn is None:
    args.sfn_arn = str(ARN(service="states",
                           resource=f"stateMachine:idseq-swipe-{os.environ['DEPLOYMENT_ENVIRONMENT']}-{args.sfn_name}-wdl"))

if args.workflow_version is None:
    github_api = "https://api.github.com"
    github_repo_api = f"{github_api}/repos/chanzuckerberg/czid-workflows"
    github_refs_api = f"{github_repo_api}/git/matching-refs/tags/{args.workflow_name}"
    github_refs = sorted(os.path.basename(ref["url"]).split("-v", 1)[1] for ref in requests.get(github_refs_api).json())
    args.workflow_version = github_refs[-1]

if parsed_sample_dir:
    samples_bucket_name = parsed_sample_dir.hostname
elif args.environment == "prod":
    samples_bucket_name = "idseq-prod-samples-us-west-2"
elif args.environment == "dev":
    samples_bucket_name = "idseq-samples-development"
else:
    samples_bucket_name = f"idseq-samples-{args.environment}"
samples_bucket = s3.Bucket(samples_bucket_name)
sample_prefix = parsed_sample_dir.path[1:] if parsed_sample_dir else f"samples/{args.project}/{args.sample}"
output_prefix = f"s3://{samples_bucket.name}/{sample_prefix}/{args.output_dir}"

fastqs = []
if not any("fastqs_0" in i for i in args.sfn_input.get("Input", {}).values()):
    fastqs = [f"s3://{s.bucket_name}/{s.key}" for s in samples_bucket.objects.filter(Prefix=f"{sample_prefix}/fastqs")]

file_ext = "fastq"
if all(f.endswith(".fasta") or f.endswith(".fa") or f.endswith(".fasta.gz") or f.endswith(".fa.gz") for f in fastqs):
    file_ext = "fasta"

docker_registry = os.getenv("DOCKER_REGISTRY", default="732052188396.dkr.ecr.us-west-2.amazonaws.com")
docker_image_id = f"{docker_registry}/{args.workflow_name}:v{args.workflow_version}"
s3_wd_uri = f"{output_prefix}/{args.workflow_name}-{args.workflow_version.split('.')[0]}"
if args.workflow_name == "short-read-mngs":
    default_sfn_input = {
        "Input": {
            "HostFilter": {
                "file_ext": file_ext,
                "nucleotide_type": "DNA",
                "host_genome": args.host_genome,
                "adapter_fasta": args.adapter_fasta,
                "star_genome": find_host_filter_index(args.host_genome, index_type="STAR_genome.tar"),
                "bowtie2_genome": find_host_filter_index(args.host_genome, index_type="bowtie2_genome.tar"),
                "human_star_genome": find_host_filter_index("human", index_type="STAR_genome.tar"),
                "human_bowtie2_genome": find_host_filter_index("human", index_type="bowtie2_genome.tar"),
                "max_input_fragments": int(args.max_input_fragments),
                "max_subsample_fragments": int(args.max_subsample_fragments),
                "docker_image_id": docker_image_id,
                "s3_wd_uri": s3_wd_uri,
            }, "NonHostAlignment": {
                "minimap2_db": index_manifest["index_generation.minimap2_index"],
                "diamond_db": index_manifest["index_generation.diamond_index"],
                "lineage_db": index_manifest["index_generation.taxid_lineages_db"],
                "accession2taxid_db": index_manifest["index_generation.accession2taxid_db"],
                "taxon_blacklist": index_manifest["index_generation.taxon_ignore_list"],
                "index_dir_suffix": args.index_version,
                "use_deuterostome_filter": args.use_deuterostome_filter,
                "use_taxon_whitelist": args.use_taxon_whitelist,
                "deuterostome_db": index_manifest["index_generation.deuterostome_taxids"],
                "docker_image_id": docker_image_id,
                "s3_wd_uri": s3_wd_uri,
            }, "Postprocess": {
                "use_deuterostome_filter": args.use_deuterostome_filter,
                "use_taxon_whitelist": args.use_taxon_whitelist,
                "nt_db": index_manifest["index_generation.nt"],
                "nt_loc_db": index_manifest["index_generation.nt_loc_db"],
                "nr_db": index_manifest["index_generation.nr"],
                "nr_loc_db": index_manifest["index_generation.nr_loc_db"],
                "lineage_db": index_manifest["index_generation.taxid_lineages_db"],
                "taxon_blacklist": index_manifest["index_generation.taxon_ignore_list"],
                "deuterostome_db": index_manifest["index_generation.deuterostome_taxids"],
                "docker_image_id": docker_image_id,
                "s3_wd_uri": s3_wd_uri,
            }, "Experimental": {
                "file_ext": file_ext,
                "use_taxon_whitelist": args.use_taxon_whitelist,
                "nt_db": index_manifest["index_generation.nt"],
                "nt_loc_db": index_manifest["index_generation.nt_loc_db"],
                "nt_info_db": index_manifest["index_generation.nt_info_db"],
                "lineage_db": index_manifest["index_generation.taxid_lineages_db"],
                "docker_image_id": docker_image_id,
                "s3_wd_uri": s3_wd_uri,
            },
        },
        "STAGES_IO_MAP_JSON": f"s3://idseq-workflows/{args.workflow_name}-v{args.workflow_version}/stage_io_map.json",
        "OutputPrefix": output_prefix

    }
else:
    default_sfn_input = {
        "Input": {
            "Run": {
                "docker_image_id": docker_image_id,
            },
        },
        "OutputPrefix": output_prefix,
    }


def deep_merge(source, destination):
    """
    Solution from: https://stackoverflow.com/questions/20656135/python-deep-merge-dictionary-data?lq=1
    """
    for key, value in source.items():
        if isinstance(value, dict):
            node = destination.setdefault(key, {})
            deep_merge(value, node)
        else:
            destination[key] = value

    return destination
    
sfn_input = deep_merge(args.sfn_input, default_sfn_input)


if fastqs:
    stage_key = list(sfn_input["Input"].keys())[0]
    sfn_input["Input"][stage_key].update({f"fastqs_{i}": fastq_url for i, fastq_url in enumerate(fastqs)})

# short-read-mngs requires fastq inputs in Experimental as well as HostFiltering
if fastqs and args.workflow_name == "short-read-mngs":
    sfn_input["Input"]["Experimental"].update({f"fastqs_{i}": fastq_url for i, fastq_url in enumerate(fastqs)})

for stage in args.stages:
    wdl_uri = f"s3://idseq-workflows/{args.workflow_name}-v{args.workflow_version}/{stage}.wdl"
    sfn_input[f"{stage.upper()}_WDL_URI"] = wdl_uri

timestamp = datetime.datetime.now().strftime("%Y-%m-%d-%H-%M-%S")
if parsed_sample_dir:
    execution_name = f"run-sfn-custom-{uuid4()}"
else:
    execution_name = f"run-sfn-{args.project}-{args.sample}-{args.pipeline_run}-{timestamp}"
logger.info(f"execution name: '{execution_name}'")

branch_run = None
if args.czid_workflows_branch:
    if args.workflow_version:
        logger.warn(
            "--workflow-version supplied alongside --czid-workflows-branch, --workflow-version will be ignored"
        )

    input_input = sfn_input["Input"]
    docker_image_ids = [input_input for stage in sfn_input["Input"].keys()]
    for stage in sfn_input["Input"].keys():
        docker_image_id = sfn_input["Input"][stage].get("docker_image_id")
        if docker_image_id:
            logger.warn(f"docker_image_id {docker_image_id} in stage {stage} supplied in --sfn-input alongside "
                        "--czid-workflows-branch, the supplied docker_image_id will be ignored")

    branch_run = BranchRun(args.workflow_name, args.czid_workflows_branch)
    wdl_uri_by_stage = branch_run.wdl_uri_by_stage
    for stage in args.stages:
        sfn_input[f"{stage.upper()}_WDL_URI"] = wdl_uri_by_stage[stage]
    for stage in sfn_input["Input"].keys():
        sfn_input["Input"][stage]["docker_image_id"] = branch_run.docker_image_id

logger.info("Starting execution for %s", execution_name)
res = sfn.start_execution(stateMachineArn=args.sfn_arn,
                          name=execution_name,
                          input=json.dumps(sfn_input))
try:
    try:
        orig_stdout, sys.stdout = sys.stdout, sys.stderr
        result = watch(watch_parser.parse_args([res["executionArn"]]), print_event_fn=print_log_line)
    finally:
        sys.stdout = orig_stdout
    print(json.dumps(result, indent=4, default=str))
    if isinstance(result, BaseException):
        raise result
except KeyboardInterrupt as e:
    logger.error("Stopping execution %s", res["executionArn"])
    print(sfn.stop_execution(executionArn=res["executionArn"], error=type(e).__name__, cause=str(e)))
    exit(1)
finally:
    if branch_run:
        branch_run.cleanup()
