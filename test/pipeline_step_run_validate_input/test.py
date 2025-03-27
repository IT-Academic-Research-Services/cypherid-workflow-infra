import os
import json
import unittest

from test.utils import run_pipeline_step


class TestPipelineStepRunValidateInput(unittest.TestCase):
    def setUp(self):
        # Specify the location of the input files.
        cur_dir = os.path.dirname(__file__)
        self.run_validate_input_wdl = os.path.join(
            cur_dir, "run_validate_input.wdl"
        )
        self.run_validate_input_basic_fastq = os.path.join(
            cur_dir, "run_validate_input_basic.fastq"
        )
        self.run_validate_input_multiline_fastq = os.path.join(
            cur_dir, "run_validate_input_multiline.fastq"
        )

    def test_basic(self):
        miniwdl_success, miniwdl_output = run_pipeline_step(
            self.run_validate_input_wdl,
            inputs={
                # Note that fastqs follow a different naming scheme than other input files.
                "fastqs_0": self.run_validate_input_basic_fastq,
                "fastqs_1": self.run_validate_input_basic_fastq,
            },
        )
        self.assertTrue(miniwdl_success)
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

    # Test multiline fastq file which is currently not supported.
    def test_badly_formatted_file(self):
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
