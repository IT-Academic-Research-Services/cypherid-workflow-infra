# type: ignore

import functools
import logging
import os

import boto3

logger = logging.getLogger()
logger.setLevel(logging.INFO)

DEPLOYMENT_ENVIRONMENT = os.environ["DEPLOYMENT_ENVIRONMENT"]

expected_parameters = {
    "MYSQL_HOST": {
        "type": "str",
        "secret": False,
        "aws_parameter_store_key": f"/idseq-{DEPLOYMENT_ENVIRONMENT}-web/RDS_ADDRESS",
    },
    "MYSQL_PORT": {
        "type": "str",
        "secret": False,
        "aws_parameter_store_key": f"/idseq-{DEPLOYMENT_ENVIRONMENT}-web/DB_PORT",
    },
    "MYSQL_DB": {
        "type": "str",
        "secret": False,
        "default": f"idseq_{DEPLOYMENT_ENVIRONMENT}",
    },
    "MYSQL_USERNAME": {
        "type": "str",
        "secret": True,
        "aws_parameter_store_key": f"/idseq-{DEPLOYMENT_ENVIRONMENT}-web/DB_USERNAME",
    },
    "MYSQL_PASSWORD": {
        "type": "str",
        "secret": True,
        "aws_parameter_store_key": f"/idseq-{DEPLOYMENT_ENVIRONMENT}-web/db_password",
    },
    "ES_HOST": {
        "type": "str",
        "secret": False,
        "aws_parameter_store_key": f"/idseq-{DEPLOYMENT_ENVIRONMENT}-web/HEATMAP_ES_ADDRESS",
    },
    "DELETE_REQUESTS_PER_SECOND": {"type": "int", "secret": False, "default": 1000},
    "EVICTION_TASK_CONCURRENCY": {"type": "int", "secret": False, "default": 6},
    "PIPELINE_RUNS_PER_TASK": {"type": "int", "secret": False, "default": 500},
    "PIPELINE_RUN_TTL_IN_DAYS": {"type": "int", "secret": False, "default": 30},
    "DRY_RUN": {"type": "bool", "secret": False, "default": False},
}


@functools.lru_cache(maxsize=None)
def get_parameters():
    """
    Fetch all parameters, giving priority to environment variables.
    """

    params_in_env = {
        param: _convert_type(os.environ[param], expected_parameters[param]["type"])
        for param in expected_parameters
        if param in os.environ
    }

    ssm_params_not_in_env = {
        param: expected_parameters[param]["aws_parameter_store_key"]
        for param in expected_parameters
        if param not in params_in_env
        and "aws_parameter_store_key" in expected_parameters[param]
    }

    params_in_ssm = {}
    if ssm_params_not_in_env:
        ssm_key_to_env_var_name = {
            expected_parameters[param]["aws_parameter_store_key"]: param
            for param in ssm_params_not_in_env
        }
        params_in_ssm = _get_params_from_ssm(
            list(ssm_params_not_in_env.values()), ssm_key_to_env_var_name
        )

    params_that_defaulted = {
        param: expected_parameters[param]["default"]
        for param in expected_parameters
        if param not in params_in_env and param not in params_in_ssm
    }
    return {**params_in_env, **params_in_ssm, **params_that_defaulted}


def get_reportable_parameters():
    """
    Return a subset of parameters that are safe to report in logs.
    """
    reportable_params = get_parameters().copy()
    for param, param_properties in expected_parameters.items():
        if param_properties["secret"]:
            reportable_params.pop(param)
    return reportable_params


def _get_params_from_ssm(parameter_keys, name_mapping):
    response = boto3.client("ssm").get_parameters(
        Names=parameter_keys, WithDecryption=True
    )
    return {
        name_mapping[parameter["Name"]]: parameter["Value"]
        for parameter in response["Parameters"]
    }


def _convert_type(param, param_type):
    if param_type == "int":
        return int(param)
    elif param_type == "bool":
        return param.lower() == "true"
    return param
