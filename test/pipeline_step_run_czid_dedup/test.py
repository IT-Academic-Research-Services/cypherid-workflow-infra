import os
import unittest

from test.utils import run_pipeline_step, get_placeholder_test_file_path


class TestRunCZIDDedup(unittest.TestCase):
    def setUp(self):
        cur_dir = os.path.dirname(__file__)
        self.run_czid_dedup_wdl = os.path.join(cur_dir, "run_czid_dedup.wdl")
        self.run_czid_dedup_basic_fa = os.path.join(
            cur_dir, "run_czid_dedup_basic.fa"
        )
        self.run_czid_dedup_with_dups_fa = os.path.join(
            cur_dir, "run_czid_dedup_with_dups.fa"
        )
        self.placeholder_test_file = get_placeholder_test_file_path()

    # Test case with no duplicates.
    def test_basic(self):
        miniwdl_success, miniwdl_output = run_pipeline_step(
            self.run_czid_dedup_wdl,
            inputs={
                "test_in_input_R1_fa": self.run_czid_dedup_basic_fa,
            },
        )
        self.assertTrue(miniwdl_success)

        with open(
            miniwdl_output["outputs"]["czid_test.test_out_output_R1_fa"]
        ) as fh:
            lines = fh.readlines()
            self.assertEqual(len(lines), 6)
            self.assertEqual(lines[0], ">MOCK_READ_ONE 00\n")
            self.assertEqual(lines[2], ">MOCK_READ_TWO 00\n")
            self.assertEqual(lines[4], ">MOCK_READ_THREE 00\n")

        with open(
            miniwdl_output["outputs"][
                "czid_test.test_out_duplicate_cluster_sizes_tsv"
            ]
        ) as fh:
            lines = fh.readlines()
            self.assertEqual(lines[0], "1\tMOCK_READ_ONE\n")
            self.assertEqual(lines[1], "1\tMOCK_READ_TWO\n")
            self.assertEqual(lines[2], "1\tMOCK_READ_THREE\n")

    # Test case with duplicate read.
    def test_with_dups(self):
        miniwdl_success, miniwdl_output = run_pipeline_step(
            self.run_czid_dedup_wdl,
            inputs={
                "test_in_input_R1_fa": self.run_czid_dedup_with_dups_fa,
            },
        )
        self.assertTrue(miniwdl_success)

        with open(
            miniwdl_output["outputs"]["czid_test.test_out_output_R1_fa"]
        ) as fh:
            lines = fh.readlines()
            self.assertEqual(len(lines), 4)
            self.assertEqual(lines[0], ">MOCK_READ_ONE 00\n")
            self.assertEqual(lines[2], ">MOCK_READ_TWO 00\n")

        with open(
            miniwdl_output["outputs"][
                "czid_test.test_out_duplicate_cluster_sizes_tsv"
            ]
        ) as fh:
            lines = fh.readlines()
            self.assertEqual(lines[0], "2\tMOCK_READ_ONE\n")
            self.assertEqual(lines[1], "1\tMOCK_READ_TWO\n")
