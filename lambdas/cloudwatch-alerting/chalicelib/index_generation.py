import json

LOG_STREAM_PREFIX = (
    "https://us-west-2.console.aws.amazon.com/cloudwatch/home?"
    "region=us-west-2#logEventViewer:group=/aws/batch/job;stream="
)


def extract_error_info(error: dict) -> str:
    primary_error = error["Error"]
    error_text = f"_Error_: {primary_error}\n"
    cause = json.loads(error["Cause"])

    # If the error was caused by something other than a batch job
    # failure, just return the state machine error text
    if "Container" not in cause.keys():
        return error_text

    primary_cause = cause["StatusReason"]
    exit_code = cause["Container"]["ExitCode"]
    log_stream = cause["Container"]["LogStreamName"]
    job_id = cause["JobId"]

    error_supplement = (
        f"_Cause_: {primary_cause}\n"
        f"_Exit Code_: {exit_code}\n"
        f"_Container Log_: {LOG_STREAM_PREFIX}{log_stream}\n"
        f"_Batch Job Id_: {job_id}\n"
    )

    return error_text + error_supplement


def handler(event, context):
    result = event["Result"]
    service = event["Caller"]["Service"]
    execution_name = event["Caller"]["Name"]
    start_time = event["StartTime"]
    end_time = event["EndTime"]
    text = (
        f"*Alert from {service}:*\n\n"
        f"_Result_: *{result}*\n"
        f"_Execution Name_: {execution_name}\n"
        f"_Start Time_: {start_time}\n"
        f"_End Time_: {end_time}\n"
    )
    if result == "Failure":
        error_message = event["Error"]
        error_text = extract_error_info(error_message)
        text += error_text
    return text
