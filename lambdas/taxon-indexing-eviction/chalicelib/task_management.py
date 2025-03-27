# type: ignore

import logging

from chalicelib.config import get_parameters
from chalicelib.es_queries import (
    get_running_deletion_tasks,
    get_completed_deletion_tasks,
    bulk_delete_pipeline_runs,
    delete_tasks,
    bulk_delete_taxons_by_pipeline_run_id,
    set_task_id_on_pipelines_being_deleted,
    bulk_delete_taxons_by_pipeline_run_id_and_background_id,
    set_task_id_on_pipelines_backgrounds_being_deleted,
    get_pipelines_being_deleted,
)
from chalicelib.change_data_detection import (
    get_pipeline_runs_deleted_from_mysql,
    get_expired_pipeline_runs_by_background_id,
)
from chalicelib.reporter import (
    report_task_statuses,
    report_task_cleanup,
    report_evictions_started,
)

logger = logging.getLogger()


def discover_and_handle_existing_deletion_tasks(dry_run=True):
    """
    Clean up existing deletion tasks
    and return the count of running tasks as well as the
    pipeline_run_ids of tasks that need to be restarted
    """
    return cleanup_existing_tasks(
        get_deletion_task_statuses(get_pipelines_being_deleted()), dry_run=dry_run
    )


def get_deletion_task_statuses(pipeline_runs):
    """
    Fetch deletion tasks from ES and return a dict of task statuses
    """

    # filter out pipeline_runs that don't have a deletion_task property
    # (they shouldn't be in this list anyways)
    pipeline_runs = [
        pipeline_run
        for pipeline_run in pipeline_runs
        if "deletion_task" in pipeline_run
    ]

    # fetch deletion tasks
    task_ids = list(
        set([pipeline_run["deletion_task"] for pipeline_run in pipeline_runs])
    )
    running_tasks = get_running_deletion_tasks(task_ids)
    completed_tasks = get_completed_deletion_tasks(task_ids)

    # TODO how do we not restart by background_id deletion tasks?
    # TODO we need to pass forward the background_ids as well to ensure we don't
    # TODO recreate deletion tasks for backgrounds that are already being deleted

    # find pipeline_runs with a deletion_task property, but no corresponding task
    # can result from a deletion task being deleted on success but the associated
    # pipeline_run failing to delete
    found_task_ids = [
        f'{task["task"]["node"]}:{task["task"]["id"]}'
        for task in running_tasks + completed_tasks
    ]
    missing_tasks = [
        {
            "id": task_id.split(":")[1],
            "node": task_id.split(":")[0],
        }
        for task_id in task_ids
        if task_id not in found_task_ids
    ]

    # find pipeline runs that have completed successfully
    # log the success and delete!
    # in the future maybe write a success message to a queue that web can read from to confirm deletion?
    succeeded_tasks = [
        task
        for task in completed_tasks
        if task["completed"] and "error" not in task and not task["response"]["failures"]
    ]
    # find deletion tasks that have failed
    # raise the failure to ops
    # auto-retry for some specific cases? Next run will retry anyways?
    failed_tasks = [
        task
        for task in completed_tasks
        if "error" in task or task["response"]["failures"]
    ]

    running_task_ids = [
        f'{task["task"]["node"]}:{task["task"]["id"]}' for task in running_tasks
    ]
    succeeded_task_ids = [
        f'{task["task"]["node"]}:{task["task"]["id"]}' for task in succeeded_tasks
    ]
    failed_task_ids = [
        f'{task["task"]["node"]}:{task["task"]["id"]}' for task in failed_tasks
    ]

    task_statuses = {
        "missing_tasks": {
            "tasks": missing_tasks,
            "pipeline_runs": [
                pipeline_run
                for pipeline_run in pipeline_runs
                if pipeline_run["deletion_task"] not in found_task_ids
            ],
        },
        "running_tasks": {
            "tasks": running_tasks,
            "pipeline_runs": [
                pipeline_run
                for pipeline_run in pipeline_runs
                if pipeline_run["deletion_task"] in running_task_ids
            ],
        },
        "succeeded_tasks": {
            "tasks": succeeded_tasks,
            "pipeline_runs": [
                pipeline_run
                for pipeline_run in pipeline_runs
                if pipeline_run["deletion_task"] in succeeded_task_ids
            ],
        },
        "failed_tasks": {
            "tasks": failed_tasks,
            "pipeline_runs": [
                pipeline_run
                for pipeline_run in pipeline_runs
                if pipeline_run["deletion_task"] in failed_task_ids
            ],
        },
    }

    report_task_statuses(task_statuses)

    return task_statuses


def cleanup_existing_tasks(tasks, dry_run=True):
    """
    Clean up existing deletion tasks and return the count
    of running tasks and the pipeline_run_ids of tasks
    that need to be restarted
    """

    if not dry_run:
        # delete succeeded tasks and their pipeline_run_records
        succeeded_task_ids = list(
            set(
                [
                    pipeline_run["deletion_task"]
                    for pipeline_run in tasks["succeeded_tasks"]["pipeline_runs"]
                ]
            )
        )
        logger.info("Deleting succeeded tasks...")
        succeeded_deletion_report = (
            {"tasks": succeeded_task_ids, "response": delete_tasks(succeeded_task_ids)}
            if succeeded_task_ids
            else {}
        )
        logger.info("Deleting succeeded pipeline runs...")
        pipeline_run_deletion_report = (
            {
                "pipeline_runs": tasks["succeeded_tasks"]["pipeline_runs"],
                "response": bulk_delete_pipeline_runs(
                    tasks["succeeded_tasks"]["pipeline_runs"]
                ),
            }
            if succeeded_task_ids
            else {}
        )

        # delete failed tasks before they are retried
        failed_task_ids = [
            pipeline_run["deletion_task"]
            for pipeline_run in tasks["failed_tasks"]["pipeline_runs"]
        ]
        logger.info("Deleting failed tasks...")
        failed_deletion_report = (
            {"tasks": failed_task_ids, "response": delete_tasks(failed_task_ids)}
            if failed_task_ids
            else {}
        )

        report_task_cleanup(
            succeeded_deletion_report,
            pipeline_run_deletion_report,
            failed_deletion_report,
        )

    return (
        # the number of currently running tasks later used to calculate capacity
        len(tasks["running_tasks"]["tasks"]),
        # the pipeline_run details of tasks that are currently running or have succeeded
        # so that we don't try to start a new task for them
        tasks["running_tasks"]["pipeline_runs"]
        + tasks["succeeded_tasks"]["pipeline_runs"],
    )


def check_capacity(running_task_count):
    """
    Given the current number of running tasks,
    return the number of tasks that can be started
    """
    return max(get_parameters()["EVICTION_TASK_CONCURRENCY"] - running_task_count, 0)


def discover_eviction_candidates(pipelines_being_deleted):
    """
    Given the list of pipelines currently being deleted by an ES task,
    return a tuple of pipelines that need to be deleted by pipeline_run_id
    and pipelines that need to be deleted by pipeline_run_id and background_id.
    Filter out pipelines that are already being deleted before returning.
    """

    logger.info("Getting pipeline runs deleted from MySQL...")

    deleted_pipeline_run_ids = [
        pr
        for pr in get_pipeline_runs_deleted_from_mysql()
        if pr not in pipelines_being_deleted
    ]

    # if an expired pipeline_run is already going to be deleted by a
    # deleted_pipeline_run_ids eviciton job, we don't need to start an expired eviction
    # task for it
    logger.info("Getting expired pipeline runs by background_id...")
    expired_pipeline_run_ids = get_expired_pipeline_runs_by_background_id(
        pipelines_being_deleted + deleted_pipeline_run_ids
    )

    return (deleted_pipeline_run_ids, expired_pipeline_run_ids)


def evict_by_pipeline_run_ids(pipeline_run_ids, remaining_capacity):
    """Start an eviction task for the given pipeline_run_ids"""

    # batch the pipeline_run_ids and only start as many tasks as we have capacity for
    pipeline_run_batches = list(
        batches(pipeline_run_ids, get_parameters()["PIPELINE_RUNS_PER_TASK"])
    )

    evictions_report = []

    for batch in pipeline_run_batches[:remaining_capacity]:
        bulk_delete_reponse = bulk_delete_taxons_by_pipeline_run_id(batch)
        set_task_id_response = {}
        if "error" not in bulk_delete_reponse:
            task_id = bulk_delete_reponse["task"]
            set_task_id_response = set_task_id_on_pipelines_being_deleted(
                task_id, batch
            )
        evictions_report.append(
            {
                "pipeline_run_ids": batch,
                "start_eviction_response": bulk_delete_reponse,
                "set_task_id_response": set_task_id_response,
            }
        )

    report_evictions_started(evictions_report, "by_pipeline_run_id")

    return max(remaining_capacity - len(pipeline_run_batches), 0)


def evict_by_pipeline_and_background_id(
    pipeline_runs_by_background_id, remaining_capacity
):
    """Start an eviction task for the given pipeline_run_ids and background_ids"""

    evictions_report = []
    for background_id, pipeline_run_ids in pipeline_runs_by_background_id.items():
        pipeline_run_batches = list(
            batches(pipeline_run_ids, get_parameters()["PIPELINE_RUNS_PER_TASK"])
        )

        for batch in pipeline_run_batches[:remaining_capacity]:
            bulk_delete_reponse = (
                bulk_delete_taxons_by_pipeline_run_id_and_background_id(
                    background_id, batch
                )
            )
            set_task_id_response = {}
            if "error" not in bulk_delete_reponse:
                task_id = bulk_delete_reponse["task"]
                set_task_id_response = (
                    set_task_id_on_pipelines_backgrounds_being_deleted(
                        task_id, background_id, batch
                    )
                )

            evictions_report.append(
                {
                    "background_id": background_id,
                    "pipeline_run_ids": batch,
                    "start_eviction_response": bulk_delete_reponse,
                    "set_task_id_response": set_task_id_response,
                }
            )

        remaining_capacity = max(remaining_capacity - len(pipeline_run_batches), 0)

    report_evictions_started(evictions_report, "by_pipeline_run_id_and_background_id")
    return remaining_capacity


def batches(lst, batch_size):
    """Yield successive n-sized chunks from l."""
    for i in range(0, len(lst), batch_size):
        yield lst[i: i + batch_size]
