#!/usr/bin/env python3

import os
import json

from botocore.exceptions import ClientError

from aegea.util import paginate, ThreadPoolExecutor
from aegea.util.aws import resources, clients, ARN

state_machines = paginate(clients.stepfunctions.get_paginator("list_state_machines"))


def s3_object(uri):
    assert uri.startswith("s3://")
    bucket, key = uri.split("/", 3)[2:]
    return resources.s3.Bucket(bucket).Object(key)


def list_executions(state_machine):
    list_executions_paginator = clients.stepfunctions.get_paginator("list_executions")
    return list(paginate(list_executions_paginator, stateMachineArn=state_machine["stateMachineArn"]))


def describe_execution(execution):
    return clients.stepfunctions.describe_execution(executionArn=execution["executionArn"])


def save_api_responses(exec_desc):
    sfn_name = ARN(exec_desc["executionArn"]).resource.split(":", 2)[1]
    exec_name = ARN(exec_desc["executionArn"]).resource.split(":", 2)[2]
    if sfn_name.startswith("idseq-prod-main-1") and exec_name.startswith("idseq-prod"):
        output_prefix = json.loads(exec_desc["input"])["OutputPrefix"]
        desc_obj = s3_object(os.path.join(output_prefix, "sfn-desc", exec_desc["executionArn"]))
        try:
            desc_obj.load()
            print(sfn_name, exec_name, "description OK")
        except ClientError:
            print("Saving", exec_name, desc_obj)
            desc_obj.put(Body=json.dumps(exec_desc, default=str).encode())
        hist_obj = s3_object(os.path.join(output_prefix, "sfn-hist", exec_desc["executionArn"]))
        try:
            hist_obj.load()
            print(sfn_name, exec_name, "history OK")
        except ClientError:
            print("Saving", exec_name, hist_obj)
            hist = clients.stepfunctions.get_execution_history(executionArn=exec_desc["executionArn"])
            hist_obj.put(Body=json.dumps(hist, default=str).encode())


with ThreadPoolExecutor(max_workers=4) as executor:
    executions = sum(executor.map(list_executions, state_machines), [])
    exec_descs = list(executor.map(describe_execution, executions))
    for i in exec_descs:
        save_api_responses(i)
