# type: ignore

from chalice import Chalice
import logging
from chalicelib.task_management import (
    discover_and_handle_existing_deletion_tasks,
    check_capacity,
    discover_eviction_candidates,
    evict_by_pipeline_run_ids,
    evict_by_pipeline_and_background_id,
)
from chalicelib.reporter import (
    report_capacity,
    report_eviction_candidates,
    deliver_final_report,
)
import chalicelib.config as config

EVICTION_TASK_CONCURRENCY = 1
PIPELINE_RUN_CONCURRENCY = 1000
DELETE_REQUESTS_PER_SECOND = 50

app = Chalice(app_name="taxon-indexing-eviction-lambda")

logger = logging.getLogger()
logger.setLevel(logging.INFO)


def handler(event, context):
    """Lambda entry point for local runs"""
    return handle_evictions(event.get("dry_run"))


@app.schedule("rate(6 hours)")
def evict(event):
    """Evict taxons for pipeline_run_ids that have been deleted"""
    dry_run = config.get_parameters()["DRY_RUN"]
    return handle_evictions(dry_run)


def handle_evictions(dry_run=False):
    """
    Entry point for the lambda
    """
    logger.info("Job parameters:")
    logger.info(config.get_reportable_parameters())

    logger.info("Discovering and handling existing deletion tasks...")
    (
        running_task_count,
        pipelines_being_deleted
    ) = discover_and_handle_existing_deletion_tasks(dry_run=dry_run)

    capacity = check_capacity(running_task_count)
    report_capacity(capacity)
    if capacity <= 0:
        return deliver_final_report()

    logger.info("Discovering eviction candidates...")
    (
        by_pipeline_candidates,
        by_pipeline_and_background_id_candidates,
    ) = discover_eviction_candidates(
        [pr["pipeline_run_id"] for pr in pipelines_being_deleted]
    )

    logger.info("Reporting eviction candidates...")
    report_eviction_candidates(
        by_pipeline_candidates, by_pipeline_and_background_id_candidates
    )

    logger.info("Starting evictions...")
    if not dry_run:
        capacity = evict_by_pipeline_run_ids(by_pipeline_candidates, capacity)
        capacity = evict_by_pipeline_and_background_id(
            by_pipeline_and_background_id_candidates, capacity
        )

    return deliver_final_report()
