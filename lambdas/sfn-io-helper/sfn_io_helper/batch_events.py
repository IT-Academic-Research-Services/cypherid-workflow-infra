import os
import json
import math
import logging
import itertools
import concurrent.futures
from typing import List

from . import batch, stepfunctions, s3_object

logger = logging.getLogger()


def list_jobs_worker(list_jobs_worker_args):
    queue, status = list_jobs_worker_args
    return [
        j["jobId"]
        for j in batch.list_jobs(jobQueue=queue, jobStatus=status)["jobSummaryList"]
    ]


def describe_jobs(queues, statuses, page_size=100):
    with concurrent.futures.ThreadPoolExecutor() as executor:
        job_ids: List = sum(
            executor.map(list_jobs_worker, itertools.product(queues, statuses)),
            [],
        )

        def describe_jobs_worker(start_index):
            return batch.describe_jobs(
                jobs=job_ids[start_index: start_index + page_size]
            )["jobs"]

        return sum(
            executor.map(describe_jobs_worker, range(0, len(job_ids), page_size)),
            [],
        )


memory_gb_per_vcpu = {"r5": 8, "m5": 4, "c5": 2}


def resize_compute_environment(queue_arn):
    queue_desc = batch.describe_job_queues(jobQueues=[queue_arn])["jobQueues"][0]
    assert queue_desc["state"] == "ENABLED"
    assert queue_desc["status"] == "VALID"
    assert len(queue_desc["computeEnvironmentOrder"]) == 1

    ce_arn = queue_desc["computeEnvironmentOrder"][0]["computeEnvironment"]
    ce_desc = batch.describe_compute_environments(computeEnvironments=[ce_arn])[
        "computeEnvironments"
    ][0]
    assert ce_desc["state"] == "ENABLED"
    if ce_desc["status"] == "UPDATING":
        pass  # Allow Lambda to fail and be retried according to standard Lambda retry policy
    assert ce_desc["status"] == "VALID"

    jobs = describe_jobs([queue_arn], ["RUNNABLE", "STARTING", "RUNNING"])
    target_vcpus = sum(job["container"]["vcpus"] for job in jobs)
    target_memory = sum(job["container"]["memory"] for job in jobs)
    for family in memory_gb_per_vcpu:
        if all(
            itype.startswith(family)
            for itype in ce_desc["computeResources"]["instanceTypes"]
        ):
            break
    else:
        raise Exception(
            "Unknown or heterogeneous compute environment instance types found"
        )
    target_vcpus = max(
        target_vcpus,
        math.ceil(target_memory / (1024 * memory_gb_per_vcpu[family])),
    )
    if target_vcpus > ce_desc["computeResources"]["maxvCpus"]:
        print(
            "CE",
            ce_arn,
            "target",
            target_vcpus,
            "exceeds max capacity",
            ce_desc["computeResources"]["maxvCpus"],
        )
        target_vcpus = ce_desc["computeResources"]["maxvCpus"]
    if target_vcpus <= ce_desc["computeResources"]["desiredvCpus"]:
        print(
            "CE",
            ce_arn,
            "at",
            ce_desc["computeResources"]["desiredvCpus"],
            "is already >= target capacity",
            target_vcpus,
        )
    elif target_vcpus > 64:
        print("Expedited scaling beyond 64 vCPUs temporarily disabled")
    else:
        print(
            "Adjusting CE",
            ce_arn,
            "from",
            ce_desc["computeResources"]["desiredvCpus"],
            "to",
            target_vcpus,
            "vcpus",
        )
        try:
            batch.update_compute_environment(
                computeEnvironment=ce_arn,
                computeResources={"desiredvCpus": target_vcpus},
            )
            print("Adjusted", ce_arn, "to", target_vcpus, "vcpus")
        except batch.exceptions.ClientException as e:
            if e.response["Error"]["Message"].startswith(
                "Manually scaling down compute environment is not supported"
            ):
                print("CE", ce_arn, "was already above target", target_vcpus)
                return
            raise


def terminate_jobs_for_stopped_sfn(
    execution_arn,
    reason=f"Parent step function execution stopped ({__name__})",
):
    history = stepfunctions.get_execution_history(executionArn=execution_arn)
    for event in sorted(history["events"], key=lambda x: x["id"]):
        if "taskSubmittedEventDetails" in event:
            if (
                event.get("taskSubmittedEventDetails", {}).get("resourceType")
                == "batch"
            ):
                job_id = json.loads(event["taskSubmittedEventDetails"]["output"])[
                    "JobId"
                ]
                logger.info(
                    "Terminating batch job %s for stopped step function %s",
                    job_id,
                    execution_arn,
                )
                batch.terminate_job(jobId=job_id, reason=reason)
                logger.info(
                    "Terminated batch job %s for stopped step function %s",
                    job_id,
                    execution_arn,
                )


def archive_sfn_history(execution_arn):
    desc = stepfunctions.describe_execution(executionArn=execution_arn)
    output_prefix = json.loads(desc["input"])["OutputPrefix"]
    s3_object(os.path.join(output_prefix, "sfn-desc", execution_arn)).put(
        Body=json.dumps(desc, default=str).encode()
    )
    hist = stepfunctions.get_execution_history(executionArn=execution_arn)
    s3_object(os.path.join(output_prefix, "sfn-hist", execution_arn)).put(
        Body=json.dumps(hist, default=str).encode()
    )
