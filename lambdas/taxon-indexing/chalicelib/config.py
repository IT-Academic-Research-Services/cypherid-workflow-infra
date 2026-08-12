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

# The web app's SSM namespace. Modern envs (seqtoid-*) publish web params under WEB_SSM_PREFIX
# (e.g. /seqtoid-staging-web) with UPPERCASE keys; fall back to the legacy /idseq-<env>-web
# namespace only when WEB_SSM_PREFIX is not set. The password follows the same UPPERCASE
# convention as the other web params -- it was `db_password` (lowercase), which does not exist in
# the seqtoid namespace and made every heatmap indexing job fail with
# KeyError: 'mysql_password'.
WEB_SSM_PREFIX = os.environ.get("WEB_SSM_PREFIX", f"/idseq-{DEPLOYMENT_ENVIRONMENT}-web")

# map each AWS parameter name to a more meaningful application parameter name
aws_parameter_names_to_local_names = {
    f"{WEB_SSM_PREFIX}/RDS_ADDRESS": "mysql_host",
    f"{WEB_SSM_PREFIX}/DB_PORT": "mysql_port",
    f"{WEB_SSM_PREFIX}/DB_USERNAME": "mysql_username",
    f"{WEB_SSM_PREFIX}/DB_PASSWORD": "mysql_password",
    f"{WEB_SSM_PREFIX}/HEATMAP_ES_ADDRESS": "es_host",
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
        # Only fall back to the legacy naming for the DB name if nothing else supplied it.
        # The env var MYSQL_DB carries the web app's real database name (e.g. `idseq_staging`) and
        # must win -- `idseq_{DEPLOYMENT_ENVIRONMENT}` would yield `idseq_seqtoid-staging`, a DB that
        # does not exist. Per the docstring, environment variables take priority, so they are merged
        # LAST (this also fixes the prior override where the legacy DB name clobbered MYSQL_DB).
        aws_params.setdefault("mysql_db", f"idseq_{DEPLOYMENT_ENVIRONMENT}")
    return {**aws_params, **env_var_params}
