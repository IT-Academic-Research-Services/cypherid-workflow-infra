# type: ignore
#
# Pure unit tests for the sfn-io-helper chalicelib (CZID-503).
#
# These exercise the AWS-free logic only -- stage input/output URI key
# derivation, the S3 URI parser, batch-detail trimming, and the idseq-dag I/O
# map invariants. Importing chalicelib constructs boto3 clients at import time,
# which only needs a region (no creds, no network); the harness sets
# AWS_DEFAULT_REGION, and we default it here so the module also runs under a
# bare `python -m unittest`. Nothing in this file touches live AWS.

import os
import unittest

os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")

from chalicelib import s3_object  # noqa: E402
from chalicelib import stage_io  # noqa: E402


class TestUriKeys(unittest.TestCase):
    def test_input_uri_key_camelcase_to_screaming_snake(self):
        self.assertEqual(stage_io.get_input_uri_key("HostFilter"), "HOST_FILTER_INPUT_URI")
        self.assertEqual(
            stage_io.get_input_uri_key("NonHostAlignment"), "NON_HOST_ALIGNMENT_INPUT_URI"
        )
        self.assertEqual(stage_io.get_input_uri_key("Run"), "RUN_INPUT_URI")

    def test_output_uri_key_camelcase_to_screaming_snake(self):
        self.assertEqual(stage_io.get_output_uri_key("HostFilter"), "HOST_FILTER_OUTPUT_URI")
        self.assertEqual(stage_io.get_output_uri_key("Postprocess"), "POSTPROCESS_OUTPUT_URI")

    def test_input_and_output_keys_differ(self):
        self.assertNotEqual(
            stage_io.get_input_uri_key("Experimental"),
            stage_io.get_output_uri_key("Experimental"),
        )


class TestS3Object(unittest.TestCase):
    def test_parses_bucket_and_key(self):
        obj = s3_object("s3://my-bucket/a/b/c.json")
        self.assertEqual(obj.bucket_name, "my-bucket")
        self.assertEqual(obj.key, "a/b/c.json")

    def test_key_may_contain_many_slashes(self):
        obj = s3_object("s3://bkt/one/two/three/four.txt")
        self.assertEqual(obj.bucket_name, "bkt")
        self.assertEqual(obj.key, "one/two/three/four.txt")

    def test_rejects_non_s3_uri(self):
        with self.assertRaises(AssertionError):
            s3_object("https://example.com/not-s3")


class TestTrimBatchJobDetails(unittest.TestCase):
    def test_clears_attempts_and_container_for_every_job(self):
        state = {
            "BatchJobDetails": {
                "HostFilter": {
                    "Attempts": [{"foo": "bar"}, {"baz": "qux"}],
                    "Container": {"vcpus": 4, "memory": 8192},
                    "Status": "SUCCEEDED",
                },
                "NonHostAlignment": {
                    "Attempts": [{"foo": "bar"}],
                    "Container": {"vcpus": 8},
                    "Status": "FAILED",
                },
            }
        }
        result = stage_io.trim_batch_job_details(state)
        for job in result["BatchJobDetails"].values():
            self.assertEqual(job["Attempts"], [])
            self.assertEqual(job["Container"], {})
        # Non-target fields are preserved.
        self.assertEqual(result["BatchJobDetails"]["HostFilter"]["Status"], "SUCCEEDED")
        self.assertEqual(result["BatchJobDetails"]["NonHostAlignment"]["Status"], "FAILED")

    def test_empty_details_is_a_noop(self):
        state = {"BatchJobDetails": {}}
        self.assertEqual(stage_io.trim_batch_job_details(state), {"BatchJobDetails": {}})


class TestIdseqDagIoMap(unittest.TestCase):
    def test_stage_order_is_the_pipeline_order(self):
        self.assertEqual(
            stage_io.idseq_dag_stages,
            ["HostFilter", "NonHostAlignment", "Postprocess", "Experimental"],
        )

    def test_stages_match_io_map_keys_and_order(self):
        # idseq_dag_stages is derived from the ordered io map; keep them in lockstep.
        self.assertEqual(stage_io.idseq_dag_stages, list(stage_io.idseq_dag_io_map))

    def test_host_filter_takes_only_raw_fastqs(self):
        # The first stage has no upstream results; its inputs are the raw fastqs.
        self.assertEqual(
            set(stage_io.idseq_dag_io_map["HostFilter"]),
            {"fastqs_0", "fastqs_1"},
        )
        for v in stage_io.idseq_dag_io_map["HostFilter"].values():
            self.assertIsNone(v)


if __name__ == "__main__":
    unittest.main()
