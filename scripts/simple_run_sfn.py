#!/usr/bin/env python3
import argparse
import json
import time
import re
from math import floor
from collections import namedtuple
from copy import deepcopy
from logging import warn
from os import path
from typing import List, Union

import boto3
from aegea.sfn import watch as _watch


sfn = boto3.client("stepfunctions")
s3 = boto3.client("s3")

AWS_ACCOUNT_IDS = {
    "dev": "732052188396",
    "staging": "732052188396",
    "prod": "745463180746",
}

parser = argparse.ArgumentParser(
    "simple_run_sfn",
    description="Runs WDLs on our default single-stage Step Function Definition",
)
parser.add_argument(
    "-n",
    "--workflow-name",
    required=True,
    help="Name of the workflow to run (i.e.) long-read-mngs",
)
parser.add_argument(
    "-v",
    "--workflow-version",
    required=True,
    help="Version of the workflow to run (i.e.) 1.0.0",
)
parser.add_argument(
    "-s",
    "--include-s3-wd-uri",
    action=argparse.BooleanOptionalAction,
    help="Include an s3_wd_uri input, useful for long-read-mngs"
)
parser.add_argument(
    "-o",
    "--output-prefix",
    required=True,
    help="S3 prefix to upload outputs (i.e.) s3://bucket-name/path-to-sample-dir/",
)
parser.add_argument(
    "-e",
    "--env",
    nargs="?",
    help="Environment to run in (dev, staging, prod)",
    default="dev",
)
parser.add_argument(
    "-f",
    "--input-file",
    action="append",
    help="Any number of JSON files that will be merged to form the input to the WDL",
)
parser.add_argument(
    "-i",
    "--input",
    action="append",
    help="Any number of key value pairs that will be merged to the input to the WDL (i.e.) 'name=value'",
)
parser.add_argument(
    "-d",
    "--do-not-interrupt",
    action=argparse.BooleanOptionalAction,
    help="Do not use SPOT instances, uses this if you don't want your run interrupted"
)
parser.add_argument(
    "-w",
    "--watch",
    action=argparse.BooleanOptionalAction,
    help="Add this flag to watch the logs of the run in your terminal",
)
parser.add_argument(
    "-m",
    "--memory",
    type=int,
    help="Memory limit for this workflow",
)


def build_wdl_input(input_files: List[str], inputs: List[str]):
    wdl_inputs = {}
    for input_file in input_files:
        with open(input_file) as f:
            wdl_inputs = dict(**wdl_inputs, **json.load(f))
    for i in inputs:
        assert "=" in i, "inputs are required to be a key value pair in the format 'key=value'"
        k, v = i.split("=")
        wdl_inputs[k] = v
    if not wdl_inputs:
        warn("you are passing no inputs into your WDL")
    return wdl_inputs


def simple_run_sfn(
    workflow_name: str,
    workflow_version: str,
    output_prefix: str,
    env: str,
    wdl_input: dict,
    watch: bool = False,
    s3_wd_uri: bool = False,
    do_not_interrupt: bool = False,
    memory: Union[int, None] = None,
):
    assert output_prefix.startswith("s3://"), "output prefix must be a path starting with s3://"
    sfn_arn = f"arn:aws:states:us-west-2:{AWS_ACCOUNT_IDS[env]}:stateMachine:idseq-swipe-{env}-default-wdl"
    execution_name = output_prefix.removeprefix("s3://").replace("/", "-") + str(floor(time.time()))

    _wdl_input = deepcopy(wdl_input)
    _wdl_input["docker_image_id"] = f"{AWS_ACCOUNT_IDS[env]}.dkr.ecr.us-west-2.amazonaws.com/{workflow_name}:v{workflow_version}"
    major_version = re.match(r'(\d+)', workflow_version).group(1)
    if s3_wd_uri:
        _wdl_input["s3_wd_uri"] = path.join(output_prefix, f"{workflow_name}-{major_version}/")

    # HACK: not all users of this script have list access to  the WDL bucket so we can fall back to `run.wdl.zip` to handle most cases
    try:
        res = s3.list_objects_v2(Bucket="idseq-workflows", Prefix=f"{workflow_name}-v{workflow_version}")
        zip_key = [obj['Key'] for obj in res['Contents'] if obj['Key'].endswith('.zip')][0]
    except Exception:
        zip_key = f'{workflow_name}-v{workflow_version}/run.wdl.zip'

    sfn_input = {
        "RUN_WDL_URI": f"s3://idseq-workflows/{zip_key}",
        "OutputPrefix": output_prefix,
        "Input": {
            "Run": _wdl_input,
        },
    }

    if do_not_interrupt:
        sfn_input['DoNotInterrupt'] = True

    if memory:
        sfn_input['RunSPOTMemory'] = memory
        sfn_input['RunEC2Memory'] = memory

    res = sfn.start_execution(
        stateMachineArn=sfn_arn,
        name=execution_name,
        input=json.dumps(sfn_input)
    )

    if watch:
        print("watching logs...")
        print("exiting this terminal will NOT cancel your workflow run")
        execution_arn = res["executionArn"]
        WatchArgs = namedtuple("WatchArgs", "execution_arn")
        _watch(WatchArgs(execution_arn))


if __name__ == "__main__":
    args = parser.parse_args()
    wdl_input = build_wdl_input(args.input_file, args.input or [])
    simple_run_sfn(
        args.workflow_name,
        args.workflow_version,
        args.output_prefix,
        args.env,
        wdl_input,
        args.watch,
        args.include_s3_wd_uri,
        args.do_not_interrupt,
        args.memory,
    )
