"""
IDseq Step Function Helper Lambda

This is the source code for an AWS Lambda function that acts as part of an IDseq AWS Step Functions state machine.

The helper Lambda performs the following functions:

- It prepares input for the WDL workflows by taking SFN input for each stage and saving it to S3 with common parameters.

- It loads AWS Batch job output into the step function state. The state machine dispatches Batch jobs to do the heavy
  lifting, but while Batch jobs can receive symbolic input via their command and environment variables, they cannot
  directly generate symbolic output. AWS Lambda can do that, so we have the Batch jobs upload their output as JSON
  to S3, and this function downloads and emits it as output. The state machine can then use this Lambda to load this
  data into its state.

- It acts as an I/O mapping adapter for legacy I/O names for different stages. The original workflows used implicit
  matching of filenames to map the outputs of one workflow to the inputs of the next. The WDL workflows require the
  mapping to be explicit, so we map the input and output names to resolve the value of the input to the next stage.

- It reacts to events emitted by the AWS Batch API whenever a new job enters RUNNABLE state. For all such events, it
  examines the state of the compute environment (CE) the job is being dispatched to, and adjusts the desiredVCPUs
  parameter for that CE to the number of vCPUs that it estimates is necessary. This is done to scale up the CE sooner
  than the Batch API otherwise would do so.

- It persists step function execution state to S3 to avoid losing this state after 90 days. To do this, it subscribes to
  events emitted by the AWS Step Functions API whenever a step function enters a RUNNING, SUCCEEDED, FAILED, TIMED_OUT,
  or ABORTED state. The state is saved to the OutputPrefix S3 directory under the `sfn-desc` and `sfn-hist` prefixes.

- It processes failures in the step function, forwarding error information and cleaning up any running Batch jobs.
"""
import os
import json
import logging

from chalice import Chalice, Rate

from sfn_io_helper import batch_events, reporting, stage_io

logger = logging.getLogger()
logger.setLevel(logging.INFO)

batch_queue_arns = os.environ.get("BATCH_QUEUE_ARNS", "").split()

app = Chalice(app_name="idseq")


@app.lambda_function("preprocess-input")
def preprocess_input(sfn_data, context):
    assert sfn_data["CurrentState"] == "PreprocessInput"
    assert sfn_data["ExecutionId"].startswith("arn:aws:states:")
    assert len(sfn_data["ExecutionId"].split(":")) == 8
    (
        _,
        _,
        _,
        aws_region,
        aws_account_id,
        _,
        state_machine_name,
        execution_name,
    ) = sfn_data["ExecutionId"].split(":")
    return stage_io.preprocess_sfn_input(
        sfn_state=sfn_data["Input"],
        aws_region=aws_region,
        aws_account_id=aws_account_id,
        state_machine_name=state_machine_name,
    )


@app.lambda_function("process-stage-output")
def process_stage_output(sfn_data, context):
    assert sfn_data["CurrentState"].endswith("ReadOutput")
    sfn_state = stage_io.read_state_from_s3(
        sfn_state=sfn_data["Input"], current_state=sfn_data["CurrentState"]
    )
    sfn_state = stage_io.trim_batch_job_details(sfn_state=sfn_state)
    return sfn_state


@app.lambda_function("handle-success")
def handle_success(sfn_data, context):
    sfn_state = sfn_data["Input"]
    reporting.notify_success(sfn_state=sfn_state)
    return sfn_state


@app.lambda_function("handle-failure")
def handle_failure(sfn_data, context):
    # This Lambda MUST raise an exception with the details of the error that caused the failure.
    sfn_state = sfn_data["Input"]
    reporting.notify_failure(sfn_state=sfn_state)
    failure_type = type(sfn_state["Error"], (Exception,), dict())
    try:
        cause = json.loads(sfn_state["Cause"])["errorMessage"]
    except Exception:
        cause = sfn_state["Cause"]
    raise failure_type(cause)


@app.on_cw_event(
    {
        "source": ["aws.batch"],
        "detail": {
            "status": ["RUNNABLE"],
            # TODO: re-enable batch queue ARN filtering once configuration information is available
            # "jobQueue": batch_queue_arns
        },
    },
    name=f"idseq-{os.environ['DEPLOYMENT_ENVIRONMENT']}-process-batch-event",
)
def process_batch_event(event):
    queue_arn = event.detail["jobQueue"]
    # assert queue_arn in batch_queue_arns
    batch_events.resize_compute_environment(queue_arn)

    reporting.emit_batch_metric_values(event)


@app.on_cw_event(
    {
        "source": ["aws.states"],
        "detail-type": ["Step Functions Execution Status Change"],
    },
    name=f"idseq-{os.environ['DEPLOYMENT_ENVIRONMENT']}-process-sfn-event",
)
def process_sfn_event(event):
    try:
        execution_arn = event.detail["executionArn"]
        if event.detail["status"] in {"ABORTED", "TIMED_OUT"}:
            batch_events.terminate_jobs_for_stopped_sfn(execution_arn)
        if f"idseq-{os.environ['DEPLOYMENT_ENVIRONMENT']}" in execution_arn:
            batch_events.archive_sfn_history(execution_arn)

        reporting.emit_sfn_metric_values(event)
    except Exception:
        logger.error(f"Error in process_sfn_event on event: {event.detail}")
        raise


@app.schedule(Rate(1, unit=Rate.MINUTES))
def report_metrics(event):
    reporting.emit_periodic_metrics()


@app.on_cw_event(
    {
        "source": ["aws.ec2"],
        "detail": {"type": ["EC2 Spot Instance Interruption Warning"]},
    }
)
def report_spot_interruption(event):
    reporting.emit_spot_interruption_metric(event)
