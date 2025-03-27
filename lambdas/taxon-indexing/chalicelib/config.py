# type: ignore

import os
import logging
import boto3

logger = logging.getLogger()
logger.setLevel(logging.INFO)

ssm = None
DEPLOYMENT_ENVIRONMENT = os.environ["DEPLOYMENT_ENVIRONMENT"]

if "AWS_CHALICE_CLI_MODE" not in os.environ and "LOCAL_MODE" not in os.environ:
    ssm = boto3.client("ssm")

# map each AWS parameter name to a more meaningful application parameter name
aws_parameter_names_to_local_names = {
    f"/idseq-{DEPLOYMENT_ENVIRONMENT}-web/RDS_ADDRESS": "mysql_host",
    f"/idseq-{DEPLOYMENT_ENVIRONMENT}-web/DB_PORT": "mysql_port",
    f"/idseq-{DEPLOYMENT_ENVIRONMENT}-web/DB_USERNAME": "mysql_username",
    f"/idseq-{DEPLOYMENT_ENVIRONMENT}-web/db_password": "mysql_password",
    f"/idseq-{DEPLOYMENT_ENVIRONMENT}-web/HEATMAP_ES_ADDRESS": "es_host",
}


def get_parameters():
    """
    Fetch all parameters, giving priority to environment variables.
    """
    # first, get all parameters from environment variables
    env_var_names = [
        local_name.upper() for local_name in aws_parameter_names_to_local_names.values()
    ] + ["MYSQL_DB"]
    env_var_params = {
        env_var_name.lower(): os.environ[env_var_name]
        for env_var_name in env_var_names
        if env_var_name in os.environ
    }

    # then, get all remaining parameters from AWS SSM
    local_names_not_in_env = set(aws_parameter_names_to_local_names.values()) - set(
        env_var_params.keys()
    )
    aws_parameter_names = [
        aws_name
        for aws_name, local_name in aws_parameter_names_to_local_names.items()
        if local_name in local_names_not_in_env
    ]

    aws_params = {}
    if aws_parameter_names:
        response = ssm.get_parameters(
            Names=list(aws_parameter_names), WithDecryption=True
        )
        aws_params = {
            aws_parameter_names_to_local_names[parameter["Name"]]: parameter["Value"]
            for parameter in response["Parameters"]
        }
        aws_params["mysql_db"] = f"idseq_{DEPLOYMENT_ENVIRONMENT}"
    return {**env_var_params, **aws_params}
