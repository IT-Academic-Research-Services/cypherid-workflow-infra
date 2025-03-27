import boto3
import json
import logging
import sys
from awsglue.utils import getResolvedOptions  # type: ignore

params = {}

glue_param_keys = {
    "optional": ["scored_taxon_counts_index_name", "pipeline_runs_index_name"],
    "required": ["input_s3_path", "input_s3_bucket", "lambda_function_name"],
}

log = logging.getLogger(__name__)


def _get_optional_glue_param_value(key, job_params, default=None):
    """
    getResolvedOptions throws an exception if a key is not present in the glue
    args, this method checks against the presence of the key before calling
    glue code.
    """

    if f"{key}" in sys.argv or f"--{key}" in sys.argv:
        job_params[key] = getResolvedOptions(sys.argv, [key])[key]
    else:
        job_params[key] = default


def _get_glue_args(required_job_param_keys, optional_job_param_keys):
    """
    Loads the job keys specified as well as the optional parameters to be
    referenced in the spark code.
    :param job_param_keys keys to load from glue context
    :return dictionary containing the job parameters (key, value)
    """
    job_params = getResolvedOptions(args=sys.argv, options=required_job_param_keys)

    for key in optional_job_param_keys:
        _get_optional_glue_param_value(key, job_params)

    return job_params


def init():
    """
    Loads the job keys specified as well as the optional parameters to be
    referenced in the spark code.
    :param job_param_keys keys to load from glue context
    :return dictionary containing the job parameters (key, value)
    """
    global params
    params = _get_glue_args(glue_param_keys["required"], glue_param_keys["optional"])
    log.info(f"args: {params}")
    # TODO validate args
    return params


def load_json_from_s3(bucket_name, key):
    """
    Loads the json file from S3
    :param bucket_name: name of the bucket
    :param key: key of the json file
    :return: json as a dictionary
    """
    s3 = boto3.resource("s3")
    obj = s3.Object(bucket_name, key)
    # TODO some validation that it is a json file
    return json.loads(obj.get()["Body"].read().decode("utf-8"))
