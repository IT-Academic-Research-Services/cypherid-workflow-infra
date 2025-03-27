"""
This AWS Lambda function receives CloudWatch logs using a subscription filter
(https://docs.aws.amazon.com/AmazonCloudWatch/latest/logs/Subscriptions.html).

The subscription filter is configured for each log group in the cloudwatch-alerting Terraform module
(idseq/terraform/modules/cloudwatch-alerting/main.tf).

Before this Lambda can function correctly, the secret referenced by SLACK_OAUTH_TOKEN_SECRET_NAME must be created
(for example, in https://console.aws.amazon.com/secretsmanager).

To send a slack notification via this lambda, include a variable in your module definition with its
value equal to module.cloudwatch-alerting.invocation_lambda. Invoking the lambda this way will cause
execution to start at handle_invocation(). You must write a function to handle the data passed this way
and transform it into a Slack message, then add that function to the ALERT_HANDLERS dictionary. The
key you use should be the same one you pass in events["Handler"].
"""
import base64
from io import BytesIO
import gzip
import json
import logging
import os
import datetime

from slack_sdk import WebClient

import boto3
from chalice import Chalice
from chalicelib import index_generation

# The Slack channel to send a message to stored in an environment variable attached to the Lambda
SLACK_CHANNEL = os.environ["SLACK_CHANNEL"]
SLACK_CHANNEL_ID = os.environ["SLACK_CHANNEL_ID"]
SLACK_OAUTH_TOKEN_SECRET_NAME = os.environ["SLACK_OAUTH_TOKEN_SECRET_NAME"]
DEPLOYMENT_ENVIRONMENT = os.environ["DEPLOYMENT_ENVIRONMENT"]

cloudwatch = boto3.client("cloudwatch")
secretsmanager = boto3.client("secretsmanager")
iam = boto3.client("iam")
slack_web_client = None


def get_slack_web_client():
    global slack_web_client
    if slack_web_client is None:
        slack_oauth_token = secretsmanager.get_secret_value(
            SecretId=SLACK_OAUTH_TOKEN_SECRET_NAME
        )["SecretString"]
        slack_web_client = WebClient(token=slack_oauth_token)
    return slack_web_client


# The specific log events on which to alert Slack/emit CloudWatch metrics, as a mapping from search strings to alert
# types. The search strings are matched verbatim in the text of the log message being scanned. The alert types are used
# for grouping in downstream APIs. These include Slack (where this Lambda uses the alert type to fold messages into
# threads) and CloudWatch metrics (where the alert type is used as the metric name). The alert type is used for
# specificity/explicit identification and in APIs which don't allow spaces or special characters in names.
TO_ALERT = {
    "AmrAlleleMismatchError": "AmrAlleleMismatchError",
    "Background computation failed for background_id": "BackgroundComputationFailed",
    "Failed to upload S3 sample": "S3UploadFailed",
    "LargeBulkUploadEvent": "LargeBulkUploadEvent",
    "Phylo tree creation failed for": "PhyloTreeCreationFailed",
    "Phylo tree failed to kick off for": "PhyloTreeKickoffFailed",
    "PhyloTreeNgFailedEvent": "PhyloTreeNgFailedEvent",
    "SampleFailedEvent": "SampleFailedEvent",
    "subprocess.CalledProcessError": "CalledProcessError",
    "UploadFailedEvent": "UploadFailedEvent",
    "WorkflowUpgradeEvent": "WorkflowUpgradeEvent",
    "TaxonIndexEvictionError": "TaxonIndexEvictionError",
}


# Mapping log group to the environment
LOG_SOURCE = {
    "ecs-logs-staging": "Staging",
    "ecs-logs-prod": "Prod",
    "/aws/batch/job": "/aws/batch/job",
}

logger = logging.getLogger()
logger.setLevel(logging.INFO)

app = Chalice(app_name="cloudwatch-alerting")

_account_alias = None


def get_account_alias():
    global _account_alias
    if _account_alias is None:
        _account_alias = iam.list_account_aliases()["AccountAliases"][0]
    return _account_alias


@app.lambda_function()
def scan_logs_and_alert(event, context):
    logs = awslogs_handler(event)

    for log in logs:
        for event in TO_ALERT:
            if event in log["message"]:
                channel_id = SLACK_CHANNEL_ID
                try:
                    msg = json.loads(log["message"])
                    if "timestamp" in msg:
                        timestamp = msg["timestamp"].split(".")[0]
                    else:
                        timestamp = datetime.datetime.fromtimestamp(
                            log["timestamp"] // 1000
                        )
                    msg = msg["message"]
                except json.JSONDecodeError:
                    msg = log
                    timestamp = datetime.datetime.fromtimestamp(
                        log["timestamp"] // 1000
                    )
                except AttributeError as e:
                    logger.error(f"AttributeError occurred: {e}")
                    logger.error(f"Log: {log}")
                    timestamp = datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
                except Exception as e:
                    logger.error(f"Exception occurred: {e}")
                    logger.error(f"Log: {log}")
                    timestamp = datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
                    msg = "Error occurred while processing logs"

                log_source = LOG_SOURCE[log["logGroup"]]
                event_name = TO_ALERT[event]

                metric_datum = prepare_metric_datum(event_name, timestamp)
                thread_topic = "[%s] [%s] %s" % (
                    get_account_alias(),
                    log_source,
                    event_name,
                )
                text = "*%s* \n *Log stream:* %s \n *Timestamp:* %s \n %s" % (
                    thread_topic,
                    log["logStream"],
                    timestamp,
                    msg,
                )

                send_slack_alert(channel_id, text, thread_topic=thread_topic)
                publish_metric(log_source, metric_datum)
    print("Processed", len(logs), "log lines")


# Handlers to deal with non AWS messages.
ALERT_HANDLERS = {"index_generation": index_generation.handler}


@app.lambda_function("custom_invocation")
def handle_invocation(event, context):
    # make sure we are properly invoked
    if not event["Handler"]:
        logger.error(
            f"Lambda invocation failed: no alert handler specified.\n\
            Event: {event}\n \
            Context: {context}"
        )
        return

    handler_name = event["Handler"]
    handler_function = ALERT_HANDLERS[handler_name]
    text = handler_function(event, context)
    channel_id = SLACK_CHANNEL_ID
    send_slack_alert(channel_id, text)


@app.on_sns_message(topic=f"{DEPLOYMENT_ENVIRONMENT}-idseq-heatmap-topic")
def handle_sns_message(event):
    event = event.to_dict()
    app.log.info(event)

    for notification in event["Records"]:
        try:
            msg = json.loads(notification["Sns"]["Message"])
            timestamp = notification["Sns"]["Timestamp"]
        except Exception as ex:
            logger.error(f"Exception occurred: {ex}")
            logger.error(f"Notification: {notification}")
            timestamp = datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
            msg = "Error occurred while processing logs"

        log_source = DEPLOYMENT_ENVIRONMENT
        alarm_name = msg["AlarmName"]
        alarm_details = f"```\n{msg}```"

        thread_topic = f"[{get_account_alias()}] [{log_source}] {alarm_name}"
        text = f"*{thread_topic}* \n *Timestamp:* {timestamp}\n {alarm_details}"

        send_slack_alert(SLACK_CHANNEL_ID, text, thread_topic=thread_topic)


def send_slack_alert(channel_id, text, thread_topic=None):
    # Timestamp of the parent message to respond in a thread to, if applicable.
    ts = None
    # If message should be sent as a thread response, check if the bot has
    # sent a message with the same alert type in the last hour and set the timestamp
    # accordingly.
    if thread_topic:
        oldest_message = str(
            (datetime.datetime.now() - datetime.timedelta(hours=2)).timestamp()
        )
        history_params = {"channel": channel_id, "oldest": oldest_message}
        channel_history = get_slack_web_client().conversations_history(**history_params)
        # messages are ordered from most recent to oldest.
        for message in channel_history["messages"]:
            if thread_topic in message["text"]:
                if (
                    message["bot_profile"]
                    and message["bot_profile"]["name"] == "idseqbot"
                ):
                    ts = message["ts"]
                    break
    slack_message = {"channel": channel_id, "text": text, "thread_ts": ts}
    response = get_slack_web_client().chat_postMessage(**slack_message)
    if response["ok"]:
        print(f"Message posted to {SLACK_CHANNEL}")


def publish_metric(log_source, metric):
    # Publishes metric to count the occurences of a log event
    cloudwatch.put_metric_data(Namespace=f"{log_source}-log-count", MetricData=[metric])


def prepare_metric_datum(event_name, timestamp):
    # To check out the restrictions of a Metric
    # Visit: https://docs.aws.amazon.com/AmazonCloudWatch/latest/APIReference/API_Metric.html
    return {
        "MetricName": "Event occurrences",
        "Dimensions": [{"Name": "EventName", "Value": event_name.replace(" ", "_")}],
        "Timestamp": timestamp,
        "Value": 1,
        "Unit": "Count",
        "StorageResolution": 60,
    }


def awslogs_handler(event):
    # Get logs
    with gzip.GzipFile(
        fileobj=BytesIO(base64.b64decode(event["awslogs"]["data"]))
    ) as decompress_stream:
        data = decompress_stream.read()
    logs = json.loads(data.decode("utf-8"))

    to_ignore = [
        "The client method is deprecated",
        "actionpack (5.1.6) lib/action_dispatch/middleware/debug_exceptions.rb:63:in",
        'ActionController::RoutingError (No route matches [GET] "/ws")',
        "binary data at marker",
        "Got new marker",
        "Known user error",
        "spades.py",
    ]

    structured_logs = []

    # Send lines
    for log in logs["logEvents"]:
        skip = False
        # Skip conditions
        for blurb in to_ignore:
            if blurb in log["message"]:
                skip = True
                break
        if skip:
            continue

        log_group_info = {
            "logGroup": logs["logGroup"],
            "logStream": logs["logStream"],
        }

        structured_logs.append(merge_dicts(log, log_group_info))

    return structured_logs


def merge_dicts(a, b, path=None):
    if path is None:
        path = []
    for key in b:
        if key in a:
            if isinstance(a[key], dict) and isinstance(b[key], dict):
                merge_dicts(a[key], b[key], path + [str(key)])
            elif a[key] == b[key]:
                pass  # same leaf value
            else:
                raise Exception(
                    "Conflict while merging metadatas and the log entry at %s"
                    % ".".join(path + [str(key)])
                )
        else:
            a[key] = b[key]
    return a
