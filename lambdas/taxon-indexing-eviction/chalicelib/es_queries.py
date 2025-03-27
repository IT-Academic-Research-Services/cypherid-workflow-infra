# type: ignore

import functools
import logging

import chalicelib.config as config
from opensearchpy import OpenSearch, NotFoundError

logger = logging.getLogger()
logger.setLevel(logging.INFO)


@functools.lru_cache(maxsize=None)
def es():
    return OpenSearch(config.get_parameters()["ES_HOST"], timeout=300)


def get_pipelines_being_deleted():
    """
    Get pipeline_runs that have an active deletion task
    """
    query = {
        "size": 10000,  # there won't be more than ~100 deletion tasks at a time
        "query": {"bool": {"filter": [{"exists": {"field": "deletion_task"}}]}},
    }

    response = es().search(body=query, index="pipeline_runs")
    return [hit["_source"] for hit in response["hits"]["hits"]]


def set_task_id_on_pipelines_being_deleted(task_id, pipeline_run_ids):
    """
    Update the pipeline_run index record to indicate
    that some scored_taxon records may be missing
    (in case of partial eviction failure).
    Future evictions will be able to reattempt if
    the pipeline_runs record is still present
    """
    query = {
        "query": {
            "bool": {"filter": [{"terms": {"pipeline_run_id": pipeline_run_ids}}]}
        },
        "script": {
            "source": """
                ctx._source.is_complete = params.is_complete;
                ctx._source.deletion_task = params.deletion_task;
            """,
            "lang": "painless",
            "params": {"is_complete": False, "deletion_task": task_id},
        },
    }

    try:
        return es().update_by_query(
            "pipeline_runs",
            query,
            # parallelize the update across the cluster
            slices="auto",
            refresh=True,
        )
    except Exception as ex:
        return {"error": str(ex)}


def set_task_id_on_pipelines_backgrounds_being_deleted(
    task_id, background_id, pipeline_run_ids
):
    """
    Update the pipeline_run index record to indicate
    that some scored_taxon records may be missing because it is currently being deleted
    or there was a previous deletion attempt that partially failed.
    Also update with the deletion task id.
    Future evictions will be able to reattempt if
    the pipeline_runs record is still present
    """
    query = {
        "query": {
            "bool": {
                "filter": [
                    {"terms": {"pipeline_run_id": pipeline_run_ids}},
                    {"term": {"background_id": background_id}},
                ]
            }
        },
        "script": {
            "source": """
                ctx._source.is_complete = params.is_complete;
                ctx._source.deletion_task = params.deletion_task;
            """,
            "lang": "painless",
            "params": {"is_complete": False, "deletion_task": task_id},
        },
    }

    try:
        return es().update_by_query(
            "pipeline_runs",
            query,
            # parallelize the update across the cluster
            slices="auto",
            refresh=True,
        )
    except Exception as ex:
        return {"error": str(ex)}


def get_completed_deletion_tasks(task_ids):
    """
    Return the details of the given deletion tasks that have completed.
    (Completed tasks are written to the .tasks index by ES)
    """
    query = {"query": {"ids": {"values": task_ids}}}

    try:
        response = es().search(index=".tasks", body=query)
        return [hit["_source"] for hit in response["hits"]["hits"]]
    except NotFoundError:
        # .tasks index doesn't exist yet
        return []


def get_running_deletion_tasks(task_ids):
    """
    Return the details of the given deletion tasks that are still running.
    (Running tasks are not yet written to the .tasks index by ES
    and must be fetched via the tasks API instead)
    """
    response = es().tasks.list(actions="*/delete/byquery")

    running_tasks = {
        task_id: task_details
        for node_id, node_details in response["nodes"].items()
        for task_id, task_details in node_details["tasks"].items()
    }

    return [
        {"task": task} for task_id, task in running_tasks.items() if task_id in task_ids
    ]


def delete_tasks(task_ids):
    """
    Delete the given tasks from the .tasks index.
    Return an error object if es throws an exception
    """
    query = {"size": 10000, "query": {"ids": {"values": task_ids}}}

    try:
        return es().delete_by_query(
            ".tasks",
            query,
            # if a task is already being deleted or
            # has been modified, delete it anyway
            conflicts="proceed",
        )
    except Exception as ex:
        return {"error": str(ex)}


def bulk_delete_taxons_by_pipeline_run_id(pipeline_run_ids):
    """
    Delete all of the scored_taxon_records for the
    given pipeline_run_ids
    """
    query = {
        "query": {
            "bool": {"filter": [{"terms": {"pipeline_run_id": pipeline_run_ids}}]}
        }
    }

    try:
        return es().delete_by_query(
            "scored_taxon_counts",
            query,
            # throttle the delete to avoid overloading the cluster
            requests_per_second=config.get_parameters()["DELETE_REQUESTS_PER_SECOND"],
            # parallelize the delete across the cluster
            slices="auto",
            # return a task id instead of waiting for the delete to complete
            wait_for_completion=False,
        )
    except Exception as ex:
        return {"error": str(ex)}


def bulk_delete_taxons_by_pipeline_run_id_and_background_id(
    background_id, pipeline_run_ids
):
    """
    Delete all of the scored_taxon_records for the
    given pipeline_run_ids
    """
    query = {
        "query": {
            "bool": {
                "filter": [
                    {"terms": {"pipeline_run_id": pipeline_run_ids}},
                    {"term": {"background_id": background_id}},
                ]
            }
        }
    }

    try:
        return es().delete_by_query(
            "scored_taxon_counts",
            query,
            # throttle the delete to avoid overloading the cluster
            requests_per_second=config.get_parameters()["DELETE_REQUESTS_PER_SECOND"],
            # parallelize the delete across the cluster
            slices="auto",
            # return a task id instead of waiting for the delete to complete
            wait_for_completion=False,
        )
    except Exception as ex:
        return {"error": str(ex)}


def bulk_delete_pipeline_runs(pipeline_runs):
    """
    Delete all of the pipeline_runs for the
    given pipeline_run_ids
    """

    bulk_body = ""
    for pipeline_run in pipeline_runs:
        es_id = f'{pipeline_run["pipeline_run_id"]}' f'_{pipeline_run["background_id"]}'
        bulk_body += f'{{"delete": {{"_index": "pipeline_runs", "_id":"{es_id}" }}}} \n'
    try:
        response = es().bulk(bulk_body)

        if response["errors"]:
            return {"error": response}

    except Exception as ex:
        return {"error": str(ex)}

    return response


def get_all_es_pipeline_runs(search_after=None):
    """
    Get all of the pipeline_runs from ES
    """
    query = {
        "size": 10000,
        "_source": ["pipeline_run_id"],
        "query": {"match_all": {}},
        "sort": {"background_id": "asc", "pipeline_run_id": "asc"},
    }

    if search_after:
        query["search_after"] = search_after

    response = es().search(body=query, index="pipeline_runs")

    hits = response["hits"]["hits"]
    if hits:
        return [
            hit["_source"]["pipeline_run_id"] for hit in hits
        ] + get_all_es_pipeline_runs(search_after=hits[-1]["sort"])

    return []


def find_expired_pipeline_runs():
    """
    Find all of the pipeline_run records that have expired and
    return their pipeline_run_ids and background_ids
    """
    # either it was last read a year ago
    # or it was created a year ago and never read
    ttl = config.get_parameters()["PIPELINE_RUN_TTL_IN_DAYS"]

    query = {
        "_source": ["pipeline_run_id", "background_id"],
        "size": 10000,
        "query": {
            "bool": {
                "should": [
                    {"range": {"last_read_at": {"lt": f"now-{ttl}d/d"}}},
                    {
                        "bool": {
                            "filter": [
                                {"range": {"created_at": {"lt": f"now-{ttl}d/d"}}}
                            ],
                            "must_not": [{"exists": {"field": "last_read_at"}}],
                        }
                    },
                ]
            }
        },
    }

    response = es().search(body=query, index="pipeline_runs")
    return [hit["_source"] for hit in response["hits"]["hits"]]
