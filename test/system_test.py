#!/usr/bin/env python3
import os
import unittest
import subprocess
import json
from zipfile import ZipFile
from io import BytesIO

import boto3  # type: ignore
import urllib3  # type: ignore
import yaml

http = urllib3.PoolManager()
s3 = boto3.resource("s3")
env_run_buckets = {
    "prod": "idseq-prod-system-test",
    "staging": "idseq-samples-staging",
    "sandbox": "idseq-samples-sandbox",
    "dev": "idseq-samples-development",
}

run_bucket = env_run_buckets[os.environ["DEPLOYMENT_ENVIRONMENT"]]


def s3_object(uri):
    assert uri.startswith("s3://")
    bucket, key = uri.split("/", 3)[2:]
    return s3.Bucket(bucket).Object(key)


class RunSFNSystemTest(unittest.TestCase):
    repo_url = (
        "https://raw.githubusercontent.com/chanzuckerberg/czid-workflows/main"
    )
    common_inputs = os.path.join(
        repo_url, "workflows/consensus-genome/test/local_test.yml"
    )
    fastqs = [
        os.path.join(
            repo_url,
            "workflows/consensus-genome/test/sample_sars-cov-2_paired_r1.fastq.gz?raw=true",
        ),
        os.path.join(
            repo_url,
            "workflows/consensus-genome/test/sample_sars-cov-2_paired_r2.fastq.gz?raw=true",
        ),
    ]
    ref_fasta = "s3://czid-public-references/consensus-genome/MN908947.3.fa"

    def test_deployed_sfn(self):
        res = http.request("GET", url=self.common_inputs)
        assert res.status == 200
        sfn_input = {"Input": {"Run": yaml.safe_load(res.data)}}
        sfn_input["Input"]["Run"].update(
            fastqs_0=self.fastqs[0],
            fastqs_1=self.fastqs[1],
            sample="system-test",
            technology="Illumina",
            ref_fasta=self.ref_fasta,
        )
        run_sfn_path = os.path.join(
            os.environ["APP_HOME"], "scripts", "run_sfn.py"
        )
        run_sfn_args = [
            run_sfn_path,
            "--workflow-name",
            "consensus-genome",
            "--sample-dir",
            f"s3://{run_bucket}/system-test",
            "--sfn-input",
        ]
        res = subprocess.check_output(run_sfn_args + [json.dumps(sfn_input)])
        sfn_output = json.loads(res.decode())["Result"]
        output_zip = (
            s3_object(
                sfn_output["consensus_genome.zip_outputs_out_output_zip"]
            )
            .get()["Body"]
            .read()
        )
        with ZipFile(BytesIO(output_zip)) as zf:
            stats = json.loads(zf.read("stats.json"))
        self.assertGreater(stats["depth_avg"], 220)

        sfn_input["Input"]["Run"].update(
            fastqs_0=sfn_output[
                "consensus_genome.compute_stats_out_output_stats"
            ]
        )
        with self.assertRaises(subprocess.CalledProcessError) as raised:
            res = subprocess.check_output(
                run_sfn_args + [json.dumps(sfn_input)]
            )
        sfn_err = json.loads(json.loads(raised.exception.output.decode()))
        self.assertEqual(
            sfn_err["executionFailedEventDetails"]["error"],
            "InvalidFileFormatError",
        )


if __name__ == "__main__":
    unittest.main()
