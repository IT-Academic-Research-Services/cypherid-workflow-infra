# type: ignore
#
# Pure unit tests for the cloudwatch-alerting Slack message formatting (CZID-503).
#
# extract_error_info only depends on the stdlib json module (chalicelib/__init__
# is empty), so this suite touches no AWS and imports no chalice framework code.

import json
import unittest

from chalicelib import index_generation


class TestExtractErrorInfo(unittest.TestCase):
    def test_non_batch_cause_returns_only_error_text(self):
        # A cause without a "Container" key is a state-machine-level error, not a
        # batch job failure -- only the primary error line is returned.
        error = {
            "Error": "States.Timeout",
            "Cause": json.dumps({"StatusReason": "some non-batch failure"}),
        }
        text = index_generation.extract_error_info(error)
        self.assertEqual(text, "_Error_: States.Timeout\n")

    def test_batch_job_cause_appends_full_supplement(self):
        error = {
            "Error": "Error",
            "Cause": json.dumps(
                {
                    "StatusReason": "Essential container in task exited",
                    "Container": {
                        "ExitCode": 137,
                        "LogStreamName": "job/default/abc123",
                    },
                    "JobId": "job-abc-123",
                }
            ),
        }
        text = index_generation.extract_error_info(error)
        self.assertIn("_Error_: Error\n", text)
        self.assertIn("_Cause_: Essential container in task exited\n", text)
        self.assertIn("_Exit Code_: 137\n", text)
        self.assertIn("_Batch Job Id_: job-abc-123\n", text)
        # The log-stream link is built from the console prefix + the stream name.
        self.assertIn(index_generation.LOG_STREAM_PREFIX + "job/default/abc123", text)

    def test_error_text_comes_first(self):
        error = {
            "Error": "Boom",
            "Cause": json.dumps(
                {
                    "StatusReason": "why",
                    "Container": {"ExitCode": 1, "LogStreamName": "s"},
                    "JobId": "j",
                }
            ),
        }
        text = index_generation.extract_error_info(error)
        self.assertTrue(text.startswith("_Error_: Boom\n"))


if __name__ == "__main__":
    unittest.main()
