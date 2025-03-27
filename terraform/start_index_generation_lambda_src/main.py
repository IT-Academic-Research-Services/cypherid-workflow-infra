import json
import os
import re
from uuid import uuid4

import boto3


def start_index_generation(event, *args):
    deployment_environment = os.environ["DEPLOYMENT_ENVIRONMENT"]
    state_machine_arn = os.environ["INDEX_GENERATION_SFN_ARN"]
    version = os.environ["INDEX_GENERATION_WORKFLOW_VERSION"]
    aws_region = os.environ["AWS_REGION"]
    aws_account_id = os.environ["AWS_ACCOUNT_ID"]
    memory = int(os.environ["MEMORY"])
    vcpu = int(os.environ["VCPU"])
    bucket = os.environ["BUCKET"]

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
    input_dict = {
        "RUN_WDL_URI": f"s3://idseq-workflows/index-generation-{version}/index_generation.wdl",
        "Input": {
            "Run": {
                "docker_image_id": f"{aws_account_id}.dkr.ecr.{aws_region}.amazonaws.com/index-generation:{version}",
                "write_to_db": True,
                "index_name": index_name,
                "env": "sandbox"
                if deployment_environment == "dev"
                else deployment_environment,
                "s3_dir": s3_dir,
                "previous_lineages": f"s3://{bucket}/{previous_lineages}",
            },
        },
        "OutputPrefix": f"s3://{bucket}/ncbi-indexes-{deployment_environment}/{index_name}/",
        "RunEC2Memory": memory,
        "RunEC2Vcpu": vcpu,
    }
    sfn.start_execution(
        stateMachineArn=state_machine_arn,
        name=f"index-generation-{index_name}-{uuid4()}",
        input=json.dumps(input_dict),
    )
