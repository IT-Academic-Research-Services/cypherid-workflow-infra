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
from unittest import mock

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


class TestIndexGenerationIoMap(unittest.TestCase):
    FANOUT_STAGES = [
        "DownloadTaxonomy", "DownloadNT", "DownloadNR",
        "CompressNR", "CompressNT", "IndexNR", "IndexNT", "IndexTaxonomy",
        "Assemble",
    ]

    def test_stage_order_is_the_fanout_pipeline(self):
        self.assertEqual(stage_io.index_generation_stages, self.FANOUT_STAGES)

    def test_stages_match_io_map_keys(self):
        self.assertEqual(
            stage_io.index_generation_stages,
            list(stage_io.index_generation_io_map),
        )

    def test_download_lanes_take_no_upstream_handoff(self):
        for stage in ("DownloadTaxonomy", "DownloadNT", "DownloadNR"):
            self.assertEqual(stage_io.index_generation_io_map[stage], {})

    def test_compress_lanes_read_their_db_and_taxid_pair(self):
        self.assertEqual(
            stage_io.index_generation_io_map["CompressNR"],
            {
                "download_out_nr": "nr",
                "download_out_accession2taxid_pdb": "accession2taxid_pdb",
                "download_out_accession2taxid_prot": "accession2taxid_prot",
            },
        )
        self.assertEqual(
            stage_io.index_generation_io_map["CompressNT"],
            {
                "download_out_nt": "nt",
                "download_out_accession2taxid_nucl_gb": "accession2taxid_nucl_gb",
                "download_out_accession2taxid_nucl_wgs": "accession2taxid_nucl_wgs",
            },
        )

    def test_index_lanes_read_their_compressed_db(self):
        self.assertEqual(stage_io.index_generation_io_map["IndexNR"], {"compress_out_nr": "nr"})
        self.assertEqual(stage_io.index_generation_io_map["IndexNT"], {"compress_out_nt": "nt"})
        self.assertEqual(
            stage_io.index_generation_io_map["IndexTaxonomy"], {"taxdump": "taxdump"}
        )

    def test_assemble_reads_both_dbs_and_all_accession2taxid(self):
        assemble = stage_io.index_generation_io_map["Assemble"]
        self.assertEqual(assemble["compress_out_nt"], "nt")
        self.assertEqual(assemble["compress_out_nr"], "nr")
        for n in ("nucl_gb", "nucl_wgs", "pdb", "prot"):
            self.assertEqual(assemble[f"accession2taxid_{n}"], f"accession2taxid_{n}")

    def test_lane_successors(self):
        self.assertEqual(
            stage_io.index_generation_lane_successors,
            {"CompressNR": "IndexNR", "CompressNT": "IndexNT"},
        )

    def test_pipeline_for_stage_routes_each_family(self):
        self.assertEqual(
            stage_io._pipeline_for_stage("CompressNR"),
            (stage_io.index_generation_stages, stage_io.index_generation_io_map),
        )
        self.assertEqual(
            stage_io._pipeline_for_stage("NonHostAlignment"),
            (stage_io.idseq_dag_stages, stage_io.idseq_dag_io_map),
        )
        self.assertEqual(stage_io._pipeline_for_stage("Run"), (None, None))

    def test_is_index_generation_detects_fanout_keys(self):
        self.assertTrue(
            stage_io._is_index_generation(
                {
                    "DOWNLOAD_NR_WDL_URI": "s3://b/index-generation-v1/download-nr.wdl",
                    "ASSEMBLE_WDL_URI": "s3://b/index-generation-v1/assemble.wdl",
                }
            )
        )
        self.assertFalse(
            stage_io._is_index_generation({"RUN_WDL_URI": "s3://b/default-v1/run.wdl"})
        )
        self.assertFalse(
            stage_io._is_index_generation(
                {"HOST_FILTER_WDL_URI": "s3://b/short-read-mngs-v1/host_filter.wdl"}
            )
        )


class TestMergeParallelOutputs(unittest.TestCase):
    def test_merge_unions_branch_results_and_writes_next_inputs(self):
        # Three Phase-1 download branches, each with only its own accumulated Result.
        branches = [
            {"OutputPrefix": "s3://o/", "Result": {
                "accession2taxid_pdb": "s3://o/pdb", "accession2taxid_prot": "s3://o/prot",
                "accession2taxid_nucl_gb": "s3://o/gb", "accession2taxid_nucl_wgs": "s3://o/wgs",
                "taxdump": "s3://o/tax"}, "BatchJobDetails": {"DownloadTaxonomy": {}}},
            {"OutputPrefix": "s3://o/", "Result": {"nt": "s3://o/nt"},
             "BatchJobDetails": {"DownloadNT": {}}},
            {"OutputPrefix": "s3://o/", "Result": {"nr": "s3://o/nr"},
             "BatchJobDetails": {"DownloadNR": {}}},
        ]
        written = {}

        def fake_get(sfn_state, stage):
            return {"docker_image_id": "img"}

        def fake_put(sfn_state, stage, stage_input):
            written[stage] = stage_input

        with mock.patch.object(stage_io, "get_stage_input", side_effect=fake_get), \
                mock.patch.object(stage_io, "put_stage_input", side_effect=fake_put):
            merged = stage_io.merge_parallel_outputs(
                branches, ["CompressNR", "CompressNT", "IndexTaxonomy"]
            )

        # Result unioned across all three branches (cross-lane visibility restored).
        self.assertEqual(merged["Result"]["nt"], "s3://o/nt")
        self.assertEqual(merged["Result"]["nr"], "s3://o/nr")
        self.assertEqual(merged["Result"]["accession2taxid_prot"], "s3://o/prot")
        self.assertEqual(
            set(merged["BatchJobDetails"]),
            {"DownloadTaxonomy", "DownloadNT", "DownloadNR"},
        )
        # Next-phase inputs resolved from the merged Result.
        self.assertEqual(written["CompressNR"]["download_out_nr"], "s3://o/nr")
        self.assertEqual(written["CompressNR"]["download_out_accession2taxid_pdb"], "s3://o/pdb")
        self.assertEqual(written["CompressNT"]["download_out_nt"], "s3://o/nt")
        self.assertEqual(written["IndexTaxonomy"]["taxdump"], "s3://o/tax")


class TestIndexGenerationUriKeys(unittest.TestCase):
    def test_input_and_output_uri_keys(self):
        self.assertEqual(stage_io.get_input_uri_key("Download"), "DOWNLOAD_INPUT_URI")
        self.assertEqual(stage_io.get_output_uri_key("Download"), "DOWNLOAD_OUTPUT_URI")
        self.assertEqual(stage_io.get_input_uri_key("Compress"), "COMPRESS_INPUT_URI")
        self.assertEqual(stage_io.get_output_uri_key("Index"), "INDEX_OUTPUT_URI")


class TestPreprocessSfnInputS3WdUri(unittest.TestCase):
    # preprocess_sfn_input writes each stage's input JSON to S3 via put_stage_input and
    # reads only WDL-URI *strings* (get_workflow_name parses the URI locally, no network).
    # We patch put_stage_input to capture the emitted per-stage inputs, so these tests run
    # AWS-free like the rest of this module. They lock the contract that s3_wd_uri is
    # injected for the WDLs that declare `String s3_wd_uri` (short-read-mngs / single-stage
    # "Run") but NOT for the index-generation sub-WDLs (download/compress/index), which do
    # not declare it and whose miniwdl input validation would otherwise reject it.

    REGION = "us-west-2"
    ACCOUNT_ID = "123456789012"

    def _run(self, sfn_state, state_machine_name, memory_stages):
        captured = {}

        def _capture(sfn_state, stage, stage_input):
            captured[stage] = stage_input

        env = {}
        for stage in memory_stages:
            for compute_env in ("SPOT", "EC2"):
                env[stage + compute_env + "MemoryDefault"] = "4096"
        with mock.patch.object(stage_io, "put_stage_input", side_effect=_capture), \
                mock.patch.dict(os.environ, env):
            stage_io.preprocess_sfn_input(
                sfn_state,
                aws_region=self.REGION,
                aws_account_id=self.ACCOUNT_ID,
                state_machine_name=state_machine_name,
            )
        return captured

    def test_index_generation_stages_get_no_s3_wd_uri(self):
        # WDL URIs live in a seqtoid-workflows-* bucket, so get_workflow_name returns the
        # key's dirname ("index-generation-v1"); the DOWNLOAD_NR_/ASSEMBLE_WDL_URI keys make
        # _is_index_generation True. Fan-out index-gen skips per-stage memory env vars, so
        # memory_stages is empty (no *MemoryDefault env needed).
        base = "s3://seqtoid-workflows-dev/index-generation-v1"
        sfn_state = {
            "OutputPrefix": "s3://out-bucket/runs/abc",
            "Input": {},
            "DOWNLOAD_NR_WDL_URI": f"{base}/download-nr.wdl",
            "ASSEMBLE_WDL_URI": f"{base}/assemble.wdl",
        }
        captured = self._run(
            sfn_state,
            state_machine_name="idseq-index-generation-main-1",
            memory_stages=[],
        )

        self.assertEqual(set(captured), set(stage_io.index_generation_stages))
        for stage, stage_input in captured.items():
            self.assertNotIn(
                "s3_wd_uri",
                stage_input,
                f"index-generation stage {stage} must not carry s3_wd_uri",
            )
            # docker_image_id is still injected for every stage.
            self.assertIn("docker_image_id", stage_input)

    def test_short_read_mngs_stages_still_get_s3_wd_uri(self):
        # No DOWNLOAD_/INDEX_WDL_URI keys -> not index-generation; the idseq-*-main-N state
        # machine name selects the idseq_dag stages.
        base = "s3://seqtoid-workflows-dev/short-read-mngs-v1"
        sfn_state = {
            "OutputPrefix": "s3://out-bucket/runs/abc",
            "Input": {},
            "HOST_FILTER_WDL_URI": f"{base}/host_filter.wdl",
        }
        captured = self._run(
            sfn_state,
            state_machine_name="idseq-mngs-main-1",
            memory_stages=stage_io.idseq_dag_stages,
        )

        expected_path = os.path.join(sfn_state["OutputPrefix"], "short-read-mngs-v1")
        self.assertEqual(
            set(captured),
            {"HostFilter", "NonHostAlignment", "Postprocess", "Experimental"},
        )
        for stage, stage_input in captured.items():
            self.assertEqual(
                stage_input.get("s3_wd_uri"),
                expected_path,
                f"short-read-mngs stage {stage} must carry s3_wd_uri",
            )

    def test_single_stage_run_workflow_gets_s3_wd_uri(self):
        # The default single-stage "Run" path (neither index-generation nor idseq-dag)
        # also declares s3_wd_uri and must keep receiving it.
        base = "s3://seqtoid-workflows-dev/consensus-genome-v1"
        sfn_state = {
            "OutputPrefix": "s3://out-bucket/runs/abc",
            "Input": {},
            "RUN_WDL_URI": f"{base}/run.wdl",
        }
        captured = self._run(
            sfn_state,
            state_machine_name="cg-wdl-1",
            memory_stages=["Run"],
        )

        expected_path = os.path.join(sfn_state["OutputPrefix"], "consensus-genome-v1")
        self.assertEqual(set(captured), {"Run"})
        self.assertEqual(captured["Run"].get("s3_wd_uri"), expected_path)


if __name__ == "__main__":
    unittest.main()
