# type: ignore

import logging
from chalicelib.config import get_reportable_parameters, get_parameters
from typing import Dict, List, Any

logger = logging.getLogger()

_warnings: List[dict] = []
_errors: List[dict] = []
_final_report: Dict[str, Any] = {
    "warnings": _warnings,
    "errors": _errors,
}


def report_task_statuses(task_statuses):
    """Report the current status of deletion tasks"""
    running_tasks_count = len(task_statuses["running_tasks"]["tasks"])
    missing_tasks_count = len(task_statuses["missing_tasks"]["tasks"])
    failed_tasks_count = len(task_statuses["failed_tasks"]["tasks"])
    succeeded_tasks_count = len(task_statuses["succeeded_tasks"]["tasks"])
    logger.info(
        "Task report: %s running tasks, %s missing tasks, %s failed tasks, %s succeeded tasks: %s",
        running_tasks_count,
        missing_tasks_count,
        failed_tasks_count,
        succeeded_tasks_count,
        task_statuses,
    )

    _final_report["task_statuses"] = task_statuses

    if failed_tasks_count > 0:
        _errors.append(
            {
                "message": "Failed tasks found",
                "details": task_statuses["failed_tasks"],
            }
        )
    if missing_tasks_count > 0:
        _errors.append(
            {
                "message": "Missing tasks found",
                "details": task_statuses["missing_tasks"],
            }
        )


def report_task_cleanup(
    succeeded_deletion_report, pipeline_run_deletion_report, failed_deletion_report
):
    """Report the results of cleaning up existing deletion tasks"""

    task_cleanup_report = {
        "succeeded": succeeded_deletion_report,
        "failed": failed_deletion_report,
        "pipeline_runs_deleted": pipeline_run_deletion_report,
    }

    logger.info("Task cleanup report: %s", task_cleanup_report)

    _final_report["task_cleanup_report"] = task_cleanup_report

    # check for errors that will be raised as warnings
    for report, report_type in zip(
        [
            succeeded_deletion_report,
            failed_deletion_report,
            pipeline_run_deletion_report,
        ],
        ["Succeeded task deletion", "Failed task deletion", "Pipeline_run cleanup"],
    ):
        if report.get("response", {}).get("error"):
            _warnings.append({"message": f"{report_type} failed", "details": report})


def report_capacity(capacity):
    """Report the current capacity for deletion tasks"""
    if capacity <= 0:
        logger.info(
            "Max deletion task concurrency %s reached. No tasks started.",
            get_parameters()["EVICTION_TASK_CONCURRENCY"]
        )
    else:
        logger.info(
            "Max deletion task concurrency %s not reached. Starting tasks... ",
            get_parameters()["EVICTION_TASK_CONCURRENCY"]
        )

    _final_report["capacity"] = capacity


def report_eviction_candidates(
    by_pipeline_candidates, by_pipeline_and_background_id_candidates
):
    """Report the pipelines that need to be deleted"""
    logger.info(
        "Deletion candidates: %s by pipeline, %s by pipeline and background id: %s",
        len(by_pipeline_candidates),
        len(by_pipeline_and_background_id_candidates),
        {
            "by_pipeline": by_pipeline_candidates,
            "by_pipeline_and_background_id": by_pipeline_and_background_id_candidates,
        },
    )

    _final_report["eviction_candidates"] = {
        "by_pipeline": by_pipeline_candidates,
        "by_pipeline_and_background_id": by_pipeline_and_background_id_candidates,
    }


def report_evictions_started(evictions_started, eviction_type):
    """Report the pipeline evictions that were started"""
    logger.info("%s evictions started: %s", eviction_type, evictions_started)

    # this is called by both pipeline_run_ids and pipeline_run_ids_by_background_id
    # so we need to append to the list rather than set the value
    evictions_started_report = _final_report.setdefault("evictions_started", {})
    evictions_started_report[eviction_type] = evictions_started

    # check for errors that will be raised as errors
    for eviction_started in evictions_started:
        if "error" in eviction_started["start_eviction_response"]:
            _errors.append(
                {"message": "Eviction start failed", "details": eviction_started}
            )
        elif "error" in eviction_started["set_task_id_response"]:
            _errors.append(
                {
                    "message": "Task ID set failed after eviction started",
                    "details": eviction_started,
                }
            )


def deliver_final_report():
    """Return the final report"""
    _final_report["params"] = get_reportable_parameters()
    if _final_report["errors"] or _final_report["warnings"]:
        logger.error
        raise Exception(f"TaxonIndexEvictionError: {_final_report}")
    return _final_report
