#!/usr/bin/env python3
import os
import json
import time
import unittest
import tempfile
import subprocess
from typing import Dict, Any

import boto3

test_wdl = """
version 1.0
task idseq_test {
  input {
    Int x = 0
  }
  command {
    :
  }
  output {
    Int y = x + 1
  }
}
"""


class TestWDL(unittest.TestCase):
    def test_basic_wdl_workflow(self):
        with tempfile.NamedTemporaryFile(suffix=".wdl") as fh:
            fh.write(test_wdl.encode())
            fh.flush()
            subprocess.check_call(["miniwdl", "run", fh.name])


class TestSFNWDL(unittest.TestCase):
    def setUp(self) -> None:
        self.s3 = boto3.resource("s3", endpoint_url="http://localhost:9000")
        self.sfn = boto3.client(
            "stepfunctions", endpoint_url="http://localhost:8083"
        )
        self.test_bucket = self.s3.create_bucket(Bucket="idseq-test")

    def test_simple_sfn_wdl_workflow(self):
        sfn_input: Dict[str, Any] = {"Input": {"HostFilter": {}}}

        for stage in (
            "host_filter",
            "non_host_alignment",
            "postprocess",
            "experimental",
        ):
            wdl_obj = self.test_bucket.Object("test.wdl")
            wdl_obj.put(Body=test_wdl.encode())
            outputs_obj = self.test_bucket.Object("output.json")
            sfn_input[
                f"{stage.upper()}_WDL_URI"
            ] = f"s3://{wdl_obj.bucket_name}/{wdl_obj.key}"
        sfn_input[
            "OutputPrefix"
        ] = f"s3://{outputs_obj.bucket_name}/{os.path.dirname(outputs_obj.key)}"

        execution_name = "idseq-test-{}".format(int(time.time()))
        sfn_arn = self.sfn.list_state_machines()["stateMachines"][0][
            "stateMachineArn"
        ]
        res = self.sfn.start_execution(
            stateMachineArn=sfn_arn,
            name=execution_name,
            input=json.dumps(sfn_input),
        )
        assert res


if __name__ == "__main__":
    unittest.main()
