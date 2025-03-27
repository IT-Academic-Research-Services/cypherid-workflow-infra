import base64
from aiobotocore.session import get_session  # type: ignore
import asyncio
import botocore
import config
import json
import logging
import math
from tenacity import (  # type: ignore
    retry,
    retry_if_result,
    stop_after_attempt,
    wait_fixed,
    after_log,
    RetryError,
)

log = logging.getLogger()

botosession = get_session()


def _is_transport_error(response):
    return response["Payload"].get("errorType") == "TransportError"


@retry(
    retry=retry_if_result(_is_transport_error),
    reraise=True,
    stop=stop_after_attempt(5),
    wait=wait_fixed(3),
    after=after_log(log, logging.DEBUG),
)
async def invoke_lambda_function(function_name, payload):
    async with botosession.create_client(
        "lambda",
        config=botocore.config.Config(
            max_pool_connections=100, read_timeout=300, connect_timeout=300
        ),
    ) as client:
        response = await client.invoke(
            FunctionName=function_name,
            InvocationType="RequestResponse",
            LogType="Tail",
            Payload=payload,
        )
        response["Payload"] = json.loads(
            (await response["Payload"].read()).decode("utf-8")
        )
        response["LogResult"] = base64.b64decode(response["LogResult"])
        return response


async def run(job_params, batch_number, index_names):
    success_count = 0
    error_response = None
    checkpoints = [math.floor(i * 0.01 * len(job_params)) for i in range(1, 101)]
    for params in job_params:
        try:
            if "scored_taxon_counts_index_name" in index_names:
                params["scored_taxon_counts_index_name"] = index_names[
                    "scored_taxon_counts_index_name"
                ]
            if "pipeline_runs_index_name" in index_names:
                params["pipeline_runs_index_name"] = index_names[
                    "pipeline_runs_index_name"
                ]
            response = await invoke_lambda_function(
                config.params["lambda_function_name"], json.dumps(params)
            )
        except botocore.exceptions.ClientError as error:
            log.exception(
                "batch %s: Couldn't invoke function %s.",
                batch_number,
                config.params["lambda_function_name"],
            )
            error_response = error
            break
        except RetryError as error:
            log.exception(
                "batch %s: Unexpected retry error: %s",
                batch_number,
                error.last_attempt.result(),
            )
            error_response = error
            break
        except Exception as error:
            log.exception("batch %s: Unexpected error: %s", batch_number, error)
            error_response = error
            break
        if "FunctionError" in response:
            log.error(
                "batch %s: Function %s returned error: %s",
                batch_number,
                config.params["lambda_function_name"],
                response,
            )
            error_response = response
            break
        success_count += 1
        if success_count in checkpoints:
            success_percent = math.floor((success_count / len(job_params)) * 100)
            log.info(
                "batch %s is %s percent complete (%s successful invocations)",
                batch_number,
                success_percent,
                success_count,
            )
    return {"success_count": success_count, "error_response": error_response}


def chunks(lst, number_of_chunks):
    """
    Yield n number of striped chunks from l.
    Source: https://stackoverflow.com/a/54802737
    """
    for i in range(0, number_of_chunks):
        yield lst[i::number_of_chunks]


async def gather_results(tasks):
    return await asyncio.gather(*tasks)


def parallel_runs(job_params, skip, index_names, concurrency):
    # loop = asyncio.get_event_loop()
    tasks = []
    batches = chunks(job_params, concurrency)
    # skip on a per-batch basis (requires that subsequent runs use the same concurrency)
    if skip:
        batches = [batch[skip:] for batch, skip in zip(batches, skip)]
    for i, batch in enumerate(batches):
        tasks.append(run(batch, i, index_names))
    return asyncio.run(gather_results(tasks))
