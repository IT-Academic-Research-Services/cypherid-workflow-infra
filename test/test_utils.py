# Test the utilities for tests.
# Also serves as documentation for how to use the test utilities to write tests.
#
# Basic test cases for the run_validate_input pipeline step are used for this test.
import os
import json
import unittest
import subprocess

from test.utils import run_pipeline_step


class TestUtils(unittest.TestCase):
    # Use test files from run_validate_input test
    def setUp(self):
        # Specify the location of the input files.
        test_dir = os.path.join(
            os.path.dirname(__file__), "pipeline_step_run_validate_input"
        )
        self.run_validate_input_wdl = os.path.join(
            test_dir, "run_validate_input.wdl"
        )
        self.run_validate_input_basic_fastq = os.path.join(
            test_dir, "run_validate_input_basic.fastq"
        )
        self.run_validate_input_multiline_fastq = os.path.join(
            test_dir, "run_validate_input_multiline.fastq"
        )
        self.missing_file = os.path.join(test_dir, "foo.bar")

    # A successful test case.
    def test_success(self):
        # Run the pipeline step via miniWDL using test utility.
        miniwdl_success, miniwdl_output = run_pipeline_step(
            self.run_validate_input_wdl,
            inputs={
                "fastqs_0": self.run_validate_input_basic_fastq,
                "fastqs_1": self.run_validate_input_basic_fastq,
            },
        )

        self.assertTrue(miniwdl_success)

        # Get the output file path from miniwdl output and verify the output.
        # In this example, the output file was a JSON file. However, you can validate the output any way you like.
        with open(
            miniwdl_output["outputs"][
                "idseq_test.test_out_validate_input_summary_json"
            ]
        ) as fh:
            validate_input_summary = json.load(fh)

        self.assertEqual(
            validate_input_summary,
            {"<50": 4, "50-500": 10, "500-10000": 2, "10000+": 0},
        )

    # A test case where the pipeline step fails.
    def test_pipeline_failure(self):
        # This fails because the input file is a multiline fastq (more than 4 lines per read), which we don't support.
        miniwdl_success, miniwdl_output = run_pipeline_step(
            self.run_validate_input_wdl,
            inputs={
                "fastqs_0": self.run_validate_input_multiline_fastq,
                "fastqs_1": self.run_validate_input_multiline_fastq,
            },
        )

        # Assert that the miniwdl call failed.
        self.assertFalse(miniwdl_success)
        # Verify that the error matches what is expected.
        self.assertEqual(miniwdl_output["error"], "InvalidFileFormatError")
        self.assertEqual(
            miniwdl_output["cause"],
            "The .fastq file run_validate_input_multiline.fastq has an invalid number of lines.",
        )

    # A test case where the error is outside of the pipeline step.
    def test_input_failure(self):
        # This fails because the files we try to pass miniWDL don't exist.
        # Since it's not a pipeline failure, it is considered an unexpected error and re-raised.
        with self.assertRaises(subprocess.CalledProcessError):
            miniwdl_success, miniwdl_output = run_pipeline_step(
                self.run_validate_input_wdl,
                inputs={
                    "fastqs_0": self.missing_file,
                    "fastqs_1": self.missing_file,
                },
            )
