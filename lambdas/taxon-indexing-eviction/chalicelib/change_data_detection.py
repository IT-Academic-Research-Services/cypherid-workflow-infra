# type: ignore

import logging

from chalicelib.sql_queries import get_all_mysql_pipeline_run_ids
from chalicelib.es_queries import get_all_es_pipeline_runs, find_expired_pipeline_runs

logger = logging.getLogger()


def get_pipeline_runs_deleted_from_mysql():
    """
    Return a list of pipeline_run_ids that are in ES but have been deleted from MySQL
    """

    sql_pipeline_run_ids = get_all_mysql_pipeline_run_ids()
    es_pipeline_run_ids = get_all_es_pipeline_runs()

    deleted_pipeline_run_ids = list(
        set(es_pipeline_run_ids) - set(sql_pipeline_run_ids)
    )

    return deleted_pipeline_run_ids


def get_expired_pipeline_runs_by_background_id(pipelines_to_exclude):
    """
    Return a dict of background_id to pipeline_run_ids for pipeline runs that have expired
    """

    expired_pipeline_runs = find_expired_pipeline_runs()

    pipeline_runs_by_background_id = {}
    for pipeline_run in expired_pipeline_runs:
        if pipeline_run["pipeline_run_id"] not in pipelines_to_exclude:
            background_id = pipeline_run["background_id"]
            pipeline_runs_with_background_id = (
                pipeline_runs_by_background_id.setdefault(background_id, [])
            )
            pipeline_runs_with_background_id.append(pipeline_run["pipeline_run_id"])

    return pipeline_runs_by_background_id
